import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import google.generativeai as genai
import json
import os
import requests
import re
import time
import sqlite3
from datetime import datetime
import unicodedata
from urllib.parse import quote

# --- CONFIGURAÇÕES ---
SPOTIFY_PLAYLIST_ID = st.secrets.get("SPOTIFY_PLAYLIST_ID") or os.getenv("SPOTIFY_PLAYLIST_ID")

# chaves / tokens vêm de secrets ou variáveis de ambiente
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

# Teste: Token do Genius funcionando?
GENIUS_ACCESS_TOKEN = st.secrets.get("GENIUS_ACCESS_TOKEN") or os.getenv("GENIUS_ACCESS_TOKEN")

SPOTIFY_CLIENT_ID = st.secrets.get("SPOTIFY_CLIENT_ID") or os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = st.secrets.get("SPOTIFY_CLIENT_SECRET") or os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = st.secrets.get("SPOTIFY_REDIRECT_URI") or os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")

# Configuração da Página
st.set_page_config(page_title="DJ IA - Pedidos (Spotify)", page_icon="🎵")

# --- BANCO DE DADOS SIMPLES PARA CACHE DE LETRAS ---
def init_db():
    """Inicializa banco de dados SQLite para cache de letras."""
    conn = sqlite3.connect('lyrics_cache.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS lyrics (
            spotify_id TEXT PRIMARY KEY,
            title TEXT,
            artist TEXT,
            lyrics TEXT,
            source TEXT,
            created_at TIMESTAMP,
            used_count INTEGER DEFAULT 0,
            last_used TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_cached_lyrics(spotify_id):
    """Busca letra no cache e atualiza timestamp."""
    conn = sqlite3.connect('lyrics_cache.db')
    c = conn.cursor()
    c.execute('SELECT lyrics, source FROM lyrics WHERE spotify_id = ?', (spotify_id,))
    result = c.fetchone()
    if result:
        # Atualiza timestamp de uso
        c.execute('UPDATE lyrics SET last_used = ?, used_count = used_count + 1 WHERE spotify_id = ?', 
                 (datetime.now(), spotify_id))
        conn.commit()
    conn.close()
    return result if result else (None, None)

def save_to_cache(spotify_id, title, artist, lyrics, source):
    """Salva letra no cache."""
    conn = sqlite3.connect('lyrics_cache.db')
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO lyrics 
        (spotify_id, title, artist, lyrics, source, created_at, used_count, last_used)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
    ''', (spotify_id, title, artist, lyrics, source, datetime.now(), datetime.now()))
    conn.commit()
    conn.close()

def clear_cache():
    """Limpa todo o cache."""
    conn = sqlite3.connect('lyrics_cache.db')
    c = conn.cursor()
    c.execute('DELETE FROM lyrics')
    conn.commit()
    conn.close()

# --- INICIALIZAÇÃO DAS APIS ---

@st.cache_resource
def setup_apis():
    # --- Gemini ---
    if not GEMINI_API_KEY:
        return None, None, "GEMINI_API_KEY não configurada."

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
    except Exception as e:
        return None, None, f"Erro ao configurar Gemini: {e}"

    # --- Spotify OAuth ---
    if not (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET):
        return model, None, (
            "Spotify OAuth não configurado. "
            "Defina SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET nos secrets."
        )

    try:
        # Configuração do Spotify OAuth
        sp_oauth = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope="playlist-modify-public playlist-modify-private",
            cache_path=".spotify_cache"
        )
        
        # Tenta obter token válido
        token_info = sp_oauth.get_cached_token()
        if not token_info:
            token_info = sp_oauth.refresh_access_token(sp_oauth.get_cached_token().get('refresh_token')) if sp_oauth.get_cached_token() else None
            
        if not token_info:
            return model, None, (
                "Não foi possível autenticar com o Spotify. "
                "Execute o script de setup primeiro para gerar o token."
            )
            
        sp = spotipy.Spotify(auth=token_info['access_token'])
        return model, sp, None

    except Exception as e:
        return None, None, f"Erro ao configurar Spotify: {e}"

model, sp, erro_setup = setup_apis()

# --- FUNÇÕES DE BUSCA DE MÚSICA ---

def buscar_musica_spotify(termo):
    """Busca música no Spotify."""
    if sp is None:
        st.error("Spotify não está configurado.")
        return None

    try:
        # Busca com filtro para músicas
        resultados = sp.search(q=termo, type="track", limit=10, market="BR")
        items = resultados["tracks"]["items"]
        
        if not items:
            return None

        # Escolhe o resultado mais relevante (primeiro)
        track = items[0]
        
        # Pega todos os artistas
        artistas = [a["name"] for a in track["artists"]]
        artista_principal = artistas[0] if artistas else ""
        
        return {
            "id": track["id"],
            "titulo": track["name"],
            "artista_principal": artista_principal,
            "artistas_completos": ", ".join(artistas),
            "artistas_lista": artistas,
            "capa": track["album"]["images"][0]["url"] if track["album"]["images"] else None,
            "explicit": track["explicit"],
            "preview_url": track.get("preview_url"),
            "album": track["album"]["name"],
            "popularidade": track.get("popularity", 0),
        }

    except Exception as e:
        st.error(f"Erro na busca do Spotify: {e}")
        return None

# --- FUNÇÕES AUXILIARES ---

def limpar_texto_para_url(texto):
    """Remove acentos e caracteres especiais para uso em URLs."""
    if not texto:
        return ""
    
    # Remove acentos
    texto = ''.join(c for c in unicodedata.normalize('NFD', str(texto))
                   if unicodedata.category(c) != 'Mn')
    
    # Remove caracteres especiais, mantém letras, números e espaços
    texto = re.sub(r'[^\w\s\-]', '', texto)
    
    # Substitui espaços por hífen
    texto = re.sub(r'\s+', '-', texto)
    
    return texto.lower()

def formatar_nome_artista(artista):
    """Formata nome do artista para busca."""
    if not artista:
        return ""
    
    # Remove features, colabs, etc.
    artista = re.sub(r'\s+feat\.?\s+.*', '', artista, flags=re.IGNORECASE)
    artista = re.sub(r'\s+com\s+.*', '', artista, flags=re.IGNORECASE)
    artista = re.sub(r'\s+&\s+.*', '', artista, flags=re.IGNORECASE)
    artista = re.sub(r'\s+x\s+.*', '', artista, flags=re.IGNORECASE)
    artista = re.sub(r'\s+ft\.?\s+.*', '', artista, flags=re.IGNORECASE)
    artista = re.sub(r'\s+featuring\s+.*', '', artista, flags=re.IGNORECASE)
    
    # Remove parênteses e conteúdo dentro
    artista = re.sub(r'\([^)]*\)', '', artista)
    artista = re.sub(r'\[[^\]]*\]', '', artista)
    
    return artista.strip()

def extrair_titulo_limpo(titulo):
    """Extrai título limpo removendo versões e parênteses."""
    if not titulo:
        return ""
    
    # Remove conteúdo entre parênteses
    titulo = re.sub(r'\([^)]*\)', '', titulo)
    titulo = re.sub(r'\[[^\]]*\]', '', titulo)
    
    # Remove "feat", "remix", etc do título
    titulo = re.sub(r'\s+feat\.?\s+.*$', '', titulo, flags=re.IGNORECASE)
    titulo = re.sub(r'\s+remix$', '', titulo, flags=re.IGNORECASE)
    titulo = re.sub(r'\s+version$', '', titulo, flags=re.IGNORECASE)
    titulo = re.sub(r'\s+edit$', '', titulo, flags=re.IGNORECASE)
    
    return titulo.strip()

# --- FUNÇÕES DE BUSCA DE LETRAS (ATUALIZADAS) ---

def buscar_letra_genius_direto(titulo, artista):
    """Busca letra no Genius usando requisição direta com token."""
    if not GENIUS_ACCESS_TOKEN:
        return None
        
    try:
        # Limpa e formata
        titulo_limpo = extrair_titulo_limpo(titulo)
        artista_limpo = formatar_nome_artista(artista)
        
        if not titulo_limpo or not artista_limpo:
            return None
        
        # Busca no Genius API
        headers = {
            'Authorization': f'Bearer {GENIUS_ACCESS_TOKEN}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Busca com query mais específica
        search_url = "https://api.genius.com/search"
        query = f"{titulo_limpo} {artista_limpo}"
        params = {
            'q': query,
            'per_page': 10
        }
        
        response = requests.get(search_url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('response') and data['response'].get('hits'):
                # Procura pelo hit mais relevante (maior pontuação)
                hits = data['response']['hits']
                
                for hit in hits:
                    result = hit['result']
                    result_title = result.get('title', '').lower()
                    result_artist = result.get('artist_names', '').lower()
                    
                    # Verifica similaridade do título e artista
                    titulo_lower = titulo_limpo.lower()
                    artista_lower = artista_limpo.lower()
                    
                    # Verifica se o artista e título são similares
                    artista_match = any(art in result_artist for art in artista_lower.split()[:2]) or \
                                  any(art in artista_lower for art in result_artist.split()[:2])
                    
                    titulo_match = titulo_lower in result_title or result_title in titulo_lower
                    
                    if artista_match and titulo_match:
                        # Agora busca a letra da música
                        song_url = f"https://api.genius.com/songs/{result['id']}"
                        song_response = requests.get(song_url, headers=headers, timeout=15)
                        
                        if song_response.status_code == 200:
                            song_data = song_response.json()
                            
                            # Tenta obter a letra
                            if 'song' in song_data:
                                # Primeiro tenta via API
                                if 'lyrics' in song_data['song']:
                                    letra = song_data['song']['lyrics']['plain']
                                else:
                                    # Se não tiver na API, tenta via URL da página
                                    song_url = result.get('url')
                                    if song_url:
                                        page_response = requests.get(song_url, headers=headers, timeout=15)
                                        if page_response.status_code == 200:
                                            # Extrai letra da página
                                            content = page_response.text
                                            # Procura pela div da letra
                                            pattern = r'<div[^>]*data-lyrics-container="true"[^>]*>(.*?)</div>'
                                            matches = re.findall(pattern, content, re.DOTALL)
                                            if matches:
                                                letra_html = ''.join(matches)
                                                letra = re.sub(r'<[^>]+>', '', letra_html)
                                                letra = re.sub(r'\[.*?\]', '', letra)  # Remove anotações
                                            else:
                                                continue
                                        else:
                                            continue
                                    else:
                                        continue
                                
                                # Limpa a letra
                                letra = re.sub(r'\n\s*\n', '\n\n', letra)
                                letra = letra.strip()
                                
                                if letra and len(letra) > 100:
                                    return letra
                        
        return None
        
    except Exception as e:
        print(f"Erro Genius: {e}")
        return None

def buscar_letra_letrasemus(titulo, artista):
    """Busca letra no site letras.mus.br com busca mais precisa."""
    try:
        # Formata artista e título
        artista_limpo = formatar_nome_artista(artista)
        titulo_limpo = extrair_titulo_limpo(titulo)
        
        if not artista_limpo or not titulo_limpo:
            return None
        
        # Prepara para URL - versão mais limpa
        artista_url = limpar_texto_para_url(artista_limpo)
        titulo_url = limpar_texto_para_url(titulo_limpo)
        
        # Tenta diferentes formatos de URL
        urls_tentativas = [
            f"https://www.letras.mus.br/{artista_url}/{titulo_url}/",
            f"https://www.letras.mus.br/{artista_url}/{titulo_url}/traducao.html",
            f"https://www.letras.mus.br/{artista_url}/",
        ]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
        }
        
        for url in urls_tentativas:
            try:
                response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
                
                if response.status_code == 200:
                    content = response.text
                    
                    # Verifica se é uma página de letra (não de busca)
                    if "letra não encontrada" in content.lower() or "buscar" in content.lower()[:1000]:
                        continue
                    
                    # Procura pela letra principal
                    padroes = [
                        r'<div[^>]*class="[^"]*cnt-letra[^"]*"[^>]*>(.*?)</div>',
                        r'<div[^>]*class="[^"]*lyric-original[^"]*"[^>]*>(.*?)</div>',
                        r'<article[^>]*>(.*?)</article>',
                    ]
                    
                    for padrao in padroes:
                        matches = re.search(padrao, content, re.DOTALL | re.IGNORECASE)
                        if matches:
                            letra_html = matches.group(1)
                            
                            # Extrai todos os parágrafos
                            paragrafos = re.findall(r'<p>(.*?)</p>', letra_html, re.DOTALL)
                            
                            if paragrafos:
                                letra_limpa = []
                                for p in paragrafos:
                                    # Remove tags HTML
                                    p_clean = re.sub(r'<[^>]+>', '', p)
                                    p_clean = re.sub(r'\s+', ' ', p_clean)
                                    p_clean = p_clean.strip()
                                    if p_clean and len(p_clean) > 10:
                                        letra_limpa.append(p_clean)
                                
                                if letra_limpa:
                                    letra = '\n\n'.join(letra_limpa)
                                    if len(letra) > 150:
                                        # Verifica se parece uma letra de música
                                        if any(word in letra.lower() for word in ['refrão', 'verso', 'estribilho', 'coro']):
                                            return letra
                                        elif len(letra_limpa) > 3:  # Pelo menos 4 parágrafos
                                            return letra
                        
                    # Alternativa: busca por divs com classe contendo "letra"
                    pattern_alternativo = r'<div[^>]*class="[^"]*letra[^"]*"[^>]*>(.*?)</div>'
                    matches = re.findall(pattern_alternativo, content, re.DOTALL | re.IGNORECASE)
                    
                    if matches:
                        letra_html = ''.join(matches)
                        letra = re.sub(r'<[^>]+>', '', letra_html)
                        letra = re.sub(r'\n\s*\n', '\n\n', letra)
                        letra = letra.strip()
                        
                        if letra and len(letra) > 150:
                            return letra
                
            except requests.RequestException:
                continue
        
        return None
        
    except Exception as e:
        print(f"Erro letras.mus.br: {e}")
        return None

def buscar_letra_vagalume(titulo, artista):
    """Busca letra no Vagalume com busca mais precisa."""
    try:
        # Limpa e formata
        titulo_limpo = extrair_titulo_limpo(titulo)
        artista_limpo = formatar_nome_artista(artista)
        
        if not artista_limpo or not titulo_limpo:
            return None
        
        url = "https://api.vagalume.com.br/search.php"
        
        # Tenta várias combinações
        combinacoes = [
            {"art": artista_limpo, "mus": titulo_limpo},
            {"art": artista_limpo, "mus": titulo_limpo.split('(')[0].strip()},  # Remove parênteses
        ]
        
        for params in combinacoes:
            params.update({"apikey": "free", "limit": 1})
            
            try:
                response = requests.get(url, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if "mus" in data and len(data["mus"]) > 0:
                        musica = data["mus"][0]
                        if musica.get("text"):
                            letra = musica.get("text", "").strip()
                            if letra and len(letra) > 100:
                                # Verifica se o título corresponde
                                titulo_api = musica.get("name", "").lower()
                                if (titulo_limpo.lower() in titulo_api or 
                                    titulo_api in titulo_limpo.lower() or
                                    len(titulo_limpo.split()) <= 2):  # Se título curto, confia mais
                                    return letra
                
            except requests.RequestException:
                continue
        
        return None
        
    except Exception as e:
        print(f"Erro Vagalume: {e}")
        return None

def buscar_letra_azlyrics(titulo, artista):
    """Busca no AZLyrics com busca mais precisa."""
    try:
        artista_limpo = formatar_nome_artista(artista)
        titulo_limpo = extrair_titulo_limpo(titulo)
        
        if not artista_limpo or not titulo_limpo:
            return None
        
        # Formata para URL do AZLyrics
        artista_url = re.sub(r'[^a-z0-9]', '', artista_limpo.lower())
        titulo_url = re.sub(r'[^a-z0-9]', '', titulo_limpo.lower())
        
        # Se muito longo, pega primeira palavra
        if len(titulo_url) > 20:
            first_word = titulo_limpo.lower().split()[0] if titulo_limpo.lower().split() else titulo_limpo.lower()
            titulo_url = re.sub(r'[^a-z0-9]', '', first_word)
        
        url = f"https://www.azlyrics.com/lyrics/{artista_url}/{titulo_url}.html"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            content = response.text
            
            # Verifica se não é página de erro
            if "page not found" in content.lower() or "404" in content.lower():
                return None
            
            # Procura pelo marcador específico do AZLyrics
            start_marker = '<!-- Usage of azlyrics.com content by any third-party lyrics provider is prohibited by our licensing agreement. Sorry about that. -->'
            
            if start_marker in content:
                start_index = content.find(start_marker) + len(start_marker)
                # Procura o próximo </div> após 5000 caracteres
                end_index = content.find('</div>', start_index + 5000)
                
                if end_index == -1:
                    end_index = start_index + 10000
                
                if end_index > start_index:
                    letra_html = content[start_index:end_index]
                    
                    # Limpa tags HTML
                    letra = re.sub(r'<[^>]+>', '', letra_html)
                    
                    # Remove linhas em branco múltiplas
                    letra = re.sub(r'\n\s*\n', '\n\n', letra)
                    letra = letra.strip()
                    
                    if letra and len(letra) > 100:
                        # Verifica se tem estrutura de letra
                        linhas = letra.split('\n')
                        if len(linhas) > 4:
                            return letra
        
        return None
        
    except Exception as e:
        print(f"Erro AZLyrics: {e}")
        return None

def buscar_letra_lyricscom(titulo, artista):
    """Busca letra no Lyrics.com como fallback."""
    try:
        artista_limpo = formatar_nome_artista(artista)
        titulo_limpo = extrair_titulo_limpo(titulo)
        
        if not artista_limpo or not titulo_limpo:
            return None
        
        # Codifica para URL
        artista_encoded = quote(artista_limpo.lower().replace(' ', '-'))
        titulo_encoded = quote(titulo_limpo.lower().replace(' ', '-'))
        
        url = f"https://www.lyrics.com/lyrics/{artista_encoded}/{titulo_encoded}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            content = response.text
            
            # Procura pela letra
            pattern = r'<pre[^>]*id="lyric-body-text"[^>]*>(.*?)</pre>'
            matches = re.search(pattern, content, re.DOTALL)
            
            if matches:
                letra_html = matches.group(1)
                letra = re.sub(r'<[^>]+>', '', letra_html)
                letra = letra.strip()
                
                if letra and len(letra) > 100:
                    return letra
        
        return None
        
    except Exception:
        return None

def buscar_letra_google(titulo, artista):
    """Tenta buscar letra via Google Custom Search como último recurso."""
    # Esta função requer Google Custom Search API key e Search Engine ID
    # Por enquanto retorna None - pode ser implementada se tiver as credenciais
    return None

def buscar_letra(titulo, artista, spotify_id, force_refresh=False):
    """Busca letra em múltiplas fontes usando as informações exatas do Spotify."""
    
    # Se force_refresh é True, ignora o cache
    if not force_refresh:
        cached_lyrics, source = get_cached_lyrics(spotify_id)
        if cached_lyrics:
            return cached_lyrics, "cache", "Letra em cache"
    
    # Lista de fontes para tentar (em ordem de prioridade)
    fontes = [
        ("genius", buscar_letra_genius_direto),
        ("letrasemus", buscar_letra_letrasemus),
        ("vagalume", buscar_letra_vagalume),
        ("azlyrics", buscar_letra_azlyrics),
        ("lyricscom", buscar_letra_lyricscom),
    ]
    
    letras_encontradas = []
    debug_info = []
    
    for fonte_nome, funcao_busca in fontes:
        try:
            # Pula Genius se não tiver token
            if fonte_nome == "genius" and not GENIUS_ACCESS_TOKEN:
                debug_info.append(f"{fonte_nome}: Token não configurado")
                continue
                
            letra = funcao_busca(titulo, artista)
            
            if letra:
                letra_limpa = letra.strip()
                tamanho = len(letra_limpa)
                
                # Validações básicas
                if tamanho < 50:
                    debug_info.append(f"{fonte_nome}: Letra muito curta ({tamanho} chars)")
                    continue
                
                # Verifica se não é conteúdo de erro
                palavras_erro = [
                    "página não encontrada", "404", "not found", 
                    "error", "buscar", "search", "resultados",
                    "letra não disponível", "lyrics not available"
                ]
                
                if any(palavra in letra_limpa.lower() for palavra in palavras_erro):
                    debug_info.append(f"{fonte_nome}: Conteúdo de erro detectado")
                    continue
                
                # Conta linhas não vazias
                linhas = [l for l in letra_limpa.split('\n') if l.strip()]
                
                if len(linhas) < 3:
                    debug_info.append(f"{fonte_nome}: Poucas linhas ({len(linhas)})")
                    continue
                
                # Adiciona à lista de letras encontradas
                letras_encontradas.append({
                    "letra": letra_limpa,
                    "fonte": fonte_nome,
                    "tamanho": tamanho,
                    "linhas": len(linhas)
                })
                
                debug_info.append(f"{fonte_nome}: Encontrada ({tamanho} chars, {len(linhas)} linhas)")
                
                # Se a fonte for muito confiável e a letra for boa, para aqui
                if fonte_nome in ["genius", "letrasemus"] and tamanho > 300 and len(linhas) > 8:
                    save_to_cache(spotify_id, titulo, artista, letra_limpa, fonte_nome)
                    return letra_limpa, fonte_nome, f"Letra encontrada via {fonte_nome}"
                
            else:
                debug_info.append(f"{fonte_nome}: Nenhuma letra encontrada")
                
        except Exception as e:
            debug_info.append(f"{fonte_nome}: Erro - {str(e)[:50]}")
            continue
    
    # Escolhe a melhor letra
    if letras_encontradas:
        # Ordena por tamanho e número de linhas
        letras_encontradas.sort(key=lambda x: (x["tamanho"], x["linhas"]), reverse=True)
        melhor = letras_encontradas[0]
        
        # Salva no cache
        save_to_cache(spotify_id, titulo, artista, melhor["letra"], melhor["fonte"])
        
        return melhor["letra"], melhor["fonte"], f"Letra encontrada via {melhor['fonte']}"
    
    # Se não encontrou nenhuma
    return None, None, f"Nenhuma letra encontrada. Debug: {' | '.join(debug_info)}"

# --- FUNÇÕES DE ANÁLISE ---

def analisar_com_ia(titulo, artista, is_explicit, letra=None):
    """Analisa a música com IA."""
    
    if letra:
        # Limpa a letra para análise
        letra_limpa = letra.strip()
        if len(letra_limpa) > 4000:
            letra_limpa = letra_limpa[:4000] + "... [continua]"
        contexto = f"LETRA COMPLETA:\n{letra_limpa}"
    else:
        contexto = "LETRA NÃO DISPONÍVEL. Decida baseado apenas no título, artista e classificação explícita."
    
    prompt = f"""
    Você é um moderador de músicas para uma festa escolar (alunos de 12 a 18 anos).

    MÚSICA:
    - Título: {titulo}
    - Artista: {artista}
    - Classificação Explícita: {"SIM" if is_explicit else "NÃO"}

    {contexto}

    REGRAS PARA ESCOLAS:
    ✅ PERMITIDO: Músicas românticas, dançantes, pop, rock suave.
    ✅ PERMITIDO: Algumas palavras fortes isoladas, se não forem o foco.
    ❌ PROIBIDO: Descrições explícitas de sexo, violência gráfica, drogas.
    ❌ PROIBIDO: Apologia ao crime, ódio, discriminação.
    ❌ PROIBIDO: Conteúdo sexual explícito ou repetitivo.

    RESPOSTA OBRIGATÓRIA EM JSON:
    {{
      "aprovado": true/false,
      "motivo": "explicação curta e clara"
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        texto = response.text.strip()
        
        # Limpa o texto
        texto = texto.replace("```json", "").replace("```", "").strip()
        
        # Encontra o JSON
        start = texto.find("{")
        end = texto.rfind("}") + 1
        
        if start >= 0 and end > start:
            json_str = texto[start:end]
            resultado = json.loads(json_str)
            return resultado
        else:
            # Fallback
            if "aprovado" in texto.lower() and "true" in texto.lower():
                return {"aprovado": True, "motivo": "Aprovado pela análise"}
            else:
                return {"aprovado": False, "motivo": "Reprovado pela análise"}
                
    except Exception as e:
        return {"aprovado": False, "motivo": f"Erro na análise: {str(e)}"}

def adicionar_na_playlist(track_id):
    """Adiciona música à playlist do Spotify."""
    if sp is None:
        st.error("Spotify não está configurado.")
        return False

    try:
        # Verifica duplicata
        playlist_tracks = sp.playlist_tracks(SPOTIFY_PLAYLIST_ID, fields="items(track(id))")
        existing_tracks = [item["track"]["id"] for item in playlist_tracks["items"]]
        
        if track_id in existing_tracks:
            return "DUPLICATE"
        
        # Adiciona
        sp.playlist_add_items(SPOTIFY_PLAYLIST_ID, [track_id])
        return "SUCCESS"
        
    except Exception as e:
        st.error(f"Erro ao adicionar: {e}")
        return "ERROR"

# --- INTERFACE PRINCIPAL ---

st.title("🎧 DJ IA - Sistema Escolar")
st.write("Analise músicas para tocar em festas escolares")

if erro_setup:
    st.error(f"⚠️ Erro de configuração: {erro_setup}")

# Status
if GENIUS_ACCESS_TOKEN:
    st.info("✅ Token Genius configurado")
else:
    st.warning("⚠️ Token Genius não configurado - buscas limitadas")

# Sidebar com controles
with st.sidebar:
    st.title("⚙️ Controles")
    
    if st.button("🧹 Limpar Cache", type="secondary"):
        clear_cache()
        st.success("Cache limpo com sucesso!")
        st.rerun()
    
    force_refresh = st.checkbox("🔄 Forçar atualização (ignorar cache)")
    
    # Estatísticas do cache
    conn = sqlite3.connect('lyrics_cache.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM lyrics')
    total_cache = c.fetchone()[0]
    c.execute('SELECT COUNT(DISTINCT artist) FROM lyrics')
    artistas_unicos = c.fetchone()[0]
    conn.close()
    
    st.metric("Letras em cache", total_cache)
    st.metric("Artistas únicos", artistas_unicos)

# Input principal
pedido = st.text_input(
    "🔍 Buscar música:",
    placeholder="Ex: Mas Você Que Eu Amo - Franco",
    help="Digite título e artista",
    key="busca_input"
)

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    buscar_btn = st.button("🎵 Buscar e Analisar", type="primary", use_container_width=True)
with col2:
    if st.button("🔄 Limpar Busca", use_container_width=True):
        st.session_state.pop('busca_input', None)
        st.rerun()
with col3:
    if st.button("🔍 Nova Busca", use_container_width=True):
        st.rerun()

if buscar_btn and pedido:
    
    with st.spinner("🔎 Buscando no Spotify..."):
        musica = buscar_musica_spotify(pedido)
    
    if musica:
        # Mostra informações
        st.subheader("📊 Música Encontrada")
        
        col_img, col_info = st.columns([1, 2])
        
        with col_img:
            if musica["capa"]:
                st.image(musica["capa"], width=150)
        
        with col_info:
            st.markdown(f"**🎵 Título:** {musica['titulo']}")
            st.markdown(f"**👤 Artista:** {musica['artistas_completos']}")
            st.markdown(f"**💿 Álbum:** {musica['album']}")
            st.markdown(f"**⭐ Popularidade:** {musica['popularidade']}/100")
            st.markdown(f"**🔗 ID Spotify:** `{musica['id']}`")
            
            if musica["explicit"]:
                st.error("⚠️ **CONTEÚDO EXPLÍCITO**")
            else:
                st.success("✅ Conteúdo Normal")
            
            if musica["preview_url"]:
                st.audio(musica["preview_url"], format="audio/mp3")
        
        # Busca letra
        st.subheader("📝 Buscando Letra")
        
        with st.spinner("🔍 Procurando letra em várias fontes..."):
            letra, fonte, status = buscar_letra(
                musica["titulo"],
                musica["artista_principal"],
                musica["id"],
                force_refresh
            )
        
        if letra:
            st.success(f"✅ {status}")
            
            # Mostra informações sobre a letra
            if fonte != "cache":
                st.info(f"📥 Letra baixada de: **{fonte}**")
            
            # Mostra um trecho da letra
            with st.expander("📜 Ver letra completa"):
                # Formata melhor a letra para exibição
                letra_formatada = letra.replace('\n\n', '\n\n')
                st.text_area("", letra_formatada, height=300, key=f"letra_{musica['id']}")
                
                # Informações sobre a letra
                st.caption(f"📏 Tamanho: {len(letra)} caracteres, {len(letra.splitlines())} linhas")
        else:
            st.warning(f"⚠️ {status}")
            st.info("A análise será feita sem a letra da música.")
        
        # Análise
        st.subheader("🤖 Análise para Escola")
        
        with st.spinner("🧠 Analisando adequação..."):
            decisao = analisar_com_ia(
                musica["titulo"],
                musica["artistas_completos"],
                musica["explicit"],
                letra
            )
        
        # Resultado
        st.markdown("---")
        
        if decisao.get("aprovado"):
            st.success("🎉 **APROVADA PARA A ESCOLA**")
            st.balloons()
            
            col_add, _ = st.columns([1, 3])
            with col_add:
                if st.button("➕ Adicionar à Playlist da Festa", type="primary", key=f"add_{musica['id']}"):
                    resultado = adicionar_na_playlist(musica["id"])
                    
                    if resultado == "SUCCESS":
                        st.success("✅ Adicionada com sucesso!")
                    elif resultado == "DUPLICATE":
                        st.info("ℹ️ Esta música já está na playlist")
                    else:
                        st.error("❌ Erro ao adicionar")
            
            st.markdown(f"**📝 Motivo:** {decisao.get('motivo', 'Sem motivo especificado')}")
        
        else:
            st.error("❌ **NÃO APROVADA PARA A ESCOLA**")
            st.markdown(f"**📝 Motivo:** {decisao.get('motivo', 'Sem motivo especificado')}")
    
    else:
        st.error("❌ Música não encontrada no Spotify.")
        st.info("Tente ser mais específico ou usar o formato: 'Título - Artista'")

# Rodapé
st.markdown("---")
st.caption("🎶 Sistema de análise musical para ambiente escolar")
st.caption("🔄 Cache de letras ativado | 🔐 Seguro | 🎯 Preciso | 🧹 Cache controlável")

# Testes rápidos no sidebar
with st.sidebar:
    st.markdown("---")
    st.subheader("🧪 Testes Rápidos")
    
    test_musicas = [
        "Bohemian Rhapsody - Queen",
        "Blinding Lights - The Weeknd",
        "Mas Você Que Eu Amo - Franco",
        "Dance Monkey - Tones and I",
        "Smells Like Teen Spirit - Nirvana",
        "Billie Jean - Michael Jackson"
    ]
    
    for test in test_musicas:
        if st.button(f"🎵 {test.split('-')[0].strip()}", key=f"test_{test}"):
            st.session_state.busca_input = test
            st.rerun()