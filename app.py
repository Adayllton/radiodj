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
            used_count INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_cached_lyrics(spotify_id):
    """Busca letra no cache."""
    conn = sqlite3.connect('lyrics_cache.db')
    c = conn.cursor()
    c.execute('SELECT lyrics, source FROM lyrics WHERE spotify_id = ?', (spotify_id,))
    result = c.fetchone()
    conn.close()
    return result if result else (None, None)

def save_to_cache(spotify_id, title, artist, lyrics, source):
    """Salva letra no cache."""
    conn = sqlite3.connect('lyrics_cache.db')
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO lyrics 
        (spotify_id, title, artist, lyrics, source, created_at, used_count)
        VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT used_count FROM lyrics WHERE spotify_id = ?), 0) + 1)
    ''', (spotify_id, title, artist, lyrics, source, datetime.now(), spotify_id))
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
            "artistas_lista": artistas,  # Lista de todos os artistas
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
    # Remove acentos
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto)
                   if unicodedata.category(c) != 'Mn')
    
    # Remove caracteres especiais, mantém letras, números e espaços
    texto = re.sub(r'[^\w\s\-]', '', texto)
    
    # Substitui espaços por hífen
    texto = re.sub(r'\s+', '-', texto)
    
    return texto.lower()

def formatar_nome_artista(artista):
    """Formata nome do artista para busca."""
    # Remove features, colabs, etc.
    artista = re.sub(r'\s+feat\.?\s+.*', '', artista, flags=re.IGNORECASE)
    artista = re.sub(r'\s+com\s+.*', '', artista, flags=re.IGNORECASE)
    artista = re.sub(r'\s+&\s+.*', '', artista, flags=re.IGNORECASE)
    artista = re.sub(r'\s+x\s+.*', '', artista, flags=re.IGNORECASE)
    
    # Remove parênteses e conteúdo dentro
    artista = re.sub(r'\([^)]*\)', '', artista)
    artista = re.sub(r'\[[^\]]*\]', '', artista)
    
    return artista.strip()

# --- FUNÇÕES DE BUSCA DE LETRAS (ATUALIZADAS) ---

def buscar_letra_genius_direto(titulo, artista):
    """Busca letra no Genius usando requisição direta com token."""
    if not GENIUS_ACCESS_TOKEN:
        return None
        
    try:
        # Limpa o texto
        titulo_limpo = re.sub(r'[^\w\s\-]', '', titulo)
        artista_limpo = formatar_nome_artista(artista)
        
        # Busca no Genius API
        headers = {
            'Authorization': f'Bearer {GENIUS_ACCESS_TOKEN}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Primeiro busca a música
        search_url = "https://api.genius.com/search"
        params = {
            'q': f"{titulo_limpo} {artista_limpo}",
            'per_page': 10
        }
        
        response = requests.get(search_url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('response') and data['response'].get('hits'):
                # Procura pelo hit mais relevante
                for hit in data['response']['hits']:
                    result = hit['result']
                    # Verifica se o título e artista são similares
                    result_title = result.get('title', '').lower()
                    result_artist = result.get('artist_names', '').lower()
                    
                    if (titulo_limpo.lower() in result_title or 
                        result_title in titulo_limpo.lower()):
                        
                        # Agora busca a letra da música
                        song_url = f"https://api.genius.com/songs/{result['id']}"
                        song_response = requests.get(song_url, headers=headers, timeout=15)
                        
                        if song_response.status_code == 200:
                            song_data = song_response.json()
                            
                            # Tenta obter a letra da estrutura da API
                            if 'song' in song_data and 'lyrics' in song_data['song']:
                                letra = song_data['song']['lyrics']['plain']
                                # Limpa tags HTML que podem vir
                                letra = re.sub(r'<[^>]+>', '', letra)
                                letra = re.sub(r'\n\s*\n', '\n\n', letra)
                                return letra.strip()
                        
        return None
        
    except Exception as e:
        print(f"Erro Genius direto: {e}")
        return None

def buscar_letra_letrasemus(titulo, artista):
    """Busca letra no site letras.mus.br com busca mais precisa."""
    try:
        # Formata artista e título para URL
        artista_limpo = formatar_nome_artista(artista)
        titulo_limpo = re.sub(r'[^\w\s\-]', '', titulo)
        
        # Remove "feat", "com", etc.
        artista_limpo = re.sub(r'\s+feat\.?\s+.*$', '', artista_limpo, flags=re.IGNORECASE)
        artista_limpo = re.sub(r'\s+com\s+.*$', '', artista_limpo, flags=re.IGNORECASE)
        artista_limpo = re.sub(r'\s+&\s+.*$', '', artista_limpo, flags=re.IGNORECASE)
        
        # Remove parênteses e colchetes
        artista_limpo = re.sub(r'\([^)]*\)', '', artista_limpo)
        artista_limpo = re.sub(r'\[[^\]]*\]', '', artista_limpo)
        
        # Remove caracteres especiais e espaços extras
        artista_limpo = artista_limpo.strip()
        
        # Prepara para URL
        artista_url = limpar_texto_para_url(artista_limpo)
        titulo_url = limpar_texto_para_url(titulo_limpo)
        
        # Tenta diferentes formatos de URL
        urls_tentativas = [
            f"https://www.letras.mus.br/{artista_url}/{titulo_url}/",
            f"https://www.letras.mus.br/{artista_url}/{titulo_url}/traducao.html",
            f"https://www.letras.mus.br/{artista_url}/{titulo_url}.html",
        ]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
            'Referer': 'https://www.google.com/',
        }
        
        for url in urls_tentativas:
            try:
                response = requests.get(url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    content = response.text
                    
                    # Verifica se encontrou a página certa (não é página de busca)
                    if "Página não encontrada" not in content and "busca" not in content.lower():
                        
                        # Múltiplos padrões para encontrar a letra
                        padroes = [
                            r'<div[^>]*class="[^"]*cnt-letra[^"]*"[^>]*>(.*?)</div>',
                            r'<div[^>]*class="[^"]*lyric-original[^"]*"[^>]*>(.*?)</div>',
                            r'<div[^>]*class="[^"]*letra-cnt[^"]*"[^>]*>(.*?)</div>',
                            r'<article[^>]*>(.*?)</article>',
                        ]
                        
                        for padrao in padroes:
                            matches = re.search(padrao, content, re.DOTALL | re.IGNORECASE)
                            if matches:
                                letra_html = matches.group(1)
                                
                                # Limpa tags HTML
                                letra = re.sub(r'<[^>]+>', '', letra_html)
                                
                                # Remove scripts e styles
                                letra = re.sub(r'<script[^>]*>.*?</script>', '', letra, flags=re.DOTALL | re.IGNORECASE)
                                letra = re.sub(r'<style[^>]*>.*?</style>', '', letra, flags=re.DOTALL | re.IGNORECASE)
                                
                                # Substitui múltiplas quebras de linha
                                letra = re.sub(r'\n\s*\n', '\n\n', letra)
                                
                                # Remove espaços no início das linhas
                                letra = '\n'.join([line.strip() for line in letra.split('\n')])
                                
                                letra = letra.strip()
                                
                                if letra and len(letra) > 150:
                                    # Verifica se realmente parece uma letra
                                    linhas = letra.split('\n')
                                    if len(linhas) > 5:
                                        return letra
                        
                        # Se não encontrou pelos padrões, tenta extrair conteúdo entre tags <p>
                        padrao_paragrafos = r'<p[^>]*>(.*?)</p>'
                        paragrafos = re.findall(padrao_paragrafos, content, re.DOTALL | re.IGNORECASE)
                        
                        if paragrafos:
                            letra_texto = []
                            for p in paragrafos:
                                p_limpo = re.sub(r'<[^>]+>', '', p)
                                p_limpo = p_limpo.strip()
                                if p_limpo and len(p_limpo) > 20:
                                    letra_texto.append(p_limpo)
                            
                            if letra_texto:
                                letra = '\n\n'.join(letra_texto)
                                if len(letra) > 150:
                                    return letra
                
            except requests.RequestException:
                continue
        
        return None
        
    except Exception as e:
        print(f"Erro no letras.mus.br: {e}")
        return None

def buscar_letra_vagalume(titulo, artista):
    """Busca letra no Vagalume com busca mais precisa."""
    try:
        # Limpa e formata
        titulo_limpo = re.sub(r'[^\w\s\-]', '', titulo)
        artista_limpo = formatar_nome_artista(artista)
        
        # Remove features
        artista_limpo = re.sub(r'\s+feat\.?\s+.*$', '', artista_limpo, flags=re.IGNORECASE)
        
        url = "https://api.vagalume.com.br/search.php"
        
        # Tenta várias combinações
        combinacoes = [
            {"art": artista_limpo, "mus": titulo_limpo},
            {"art": artista_limpo.split()[0] if artista_limpo.split() else artista_limpo, "mus": titulo_limpo},
        ]
        
        for params in combinacoes:
            params.update({"apikey": "free", "limit": 3})
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if "mus" in data and len(data["mus"]) > 0:
                    # Procura a música mais parecida
                    for musica in data["mus"]:
                        if musica.get("text"):
                            letra = musica.get("text", "").strip()
                            if letra and len(letra) > 100:
                                # Verifica se é realmente a música certa
                                titulo_api = musica.get("name", "").lower()
                                if (titulo_limpo.lower() in titulo_api or 
                                    titulo_api in titulo_limpo.lower()):
                                    return letra
                    
                    # Se não encontrou exato, pega a primeira com letra
                    for musica in data["mus"]:
                        if musica.get("text"):
                            letra = musica.get("text", "").strip()
                            if letra and len(letra) > 100:
                                return letra
        
        return None
        
    except Exception as e:
        print(f"Erro no Vagalume: {e}")
        return None

def buscar_letra_azlyrics(titulo, artista):
    """Busca no AZLyrics com busca mais precisa."""
    try:
        # Formata para URL do AZLyrics
        artista_limpo = formatar_nome_artista(artista)
        titulo_limpo = titulo.lower()
        
        # Remove features e colaborações
        artista_limpo = re.sub(r'\s+feat\.?\s+.*$', '', artista_limpo, flags=re.IGNORECASE)
        artista_limpo = re.sub(r'\s+ft\.?\s+.*$', '', artista_limpo, flags=re.IGNORECASE)
        artista_limpo = re.sub(r'\s+with\s+.*$', '', artista_limpo, flags=re.IGNORECASE)
        
        # Remove tudo após "and", "&", "y" para pegar artista principal
        artista_limpo = re.split(r'\s+and\s+|\s+&\s+|\s+y\s+', artista_limpo)[0]
        
        # Remove caracteres não alfanuméricos (exceto hífen)
        artista_url = re.sub(r'[^a-z0-9]', '', artista_limpo.lower())
        titulo_url = re.sub(r'[^a-z0-9]', '', titulo_limpo)
        
        # Se o título for muito longo, pega as primeiras palavras
        if len(titulo_url) > 30:
            titulo_url = re.sub(r'[^a-z0-9]', '', titulo_limpo.split()[0] if titulo_limpo.split() else titulo_limpo)
        
        url = f"https://www.azlyrics.com/lyrics/{artista_url}/{titulo_url}.html"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.azlyrics.com/',
            'DNT': '1',
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            content = response.text
            
            # Procura pelo padrão específico do AZLyrics
            start_marker = '<!-- Usage of azlyrics.com content by any third-party lyrics provider is prohibited by our licensing agreement. Sorry about that. -->'
            end_marker = '</div>'
            
            if start_marker in content:
                start_index = content.find(start_marker) + len(start_marker)
                # Procura o próximo </div> após o marcador
                end_index = content.find(end_marker, start_index)
                
                if end_index > start_index:
                    letra_html = content[start_index:end_index]
                    
                    # Limpa tags HTML
                    letra = re.sub(r'<[^>]+>', '', letra_html)
                    
                    # Remove múltiplos espaços e quebras de linha
                    letra = re.sub(r'\s+', ' ', letra)
                    letra = re.sub(r'\n\s*\n', '\n\n', letra)
                    
                    letra = letra.strip()
                    
                    if letra and len(letra) > 100:
                        # Verifica se parece uma letra (tem múltiplas linhas)
                        linhas = letra.split('\n')
                        if len(linhas) > 3:
                            return letra
        
        return None
        
    except Exception as e:
        print(f"Erro no AZLyrics: {e}")
        return None

def buscar_letra_lyricscom(titulo, artista):
    """Busca letra no Lyrics.com como fallback adicional."""
    try:
        artista_limpo = formatar_nome_artista(artista)
        titulo_limpo = re.sub(r'[^\w\s\-]', '', titulo)
        
        # Formata para URL
        artista_url = re.sub(r'[^\w\s\-]', '', artista_limpo.replace(' ', '-')).lower()
        titulo_url = re.sub(r'[^\w\s\-]', '', titulo_limpo.replace(' ', '-')).lower()
        
        url = f"https://www.lyrics.com/lyric/{titulo_url}/{artista_url}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            content = response.text
            
            # Procura pela letra
            padrao = r'<pre[^>]*id="lyric-body-text"[^>]*>(.*?)</pre>'
            matches = re.search(padrao, content, re.DOTALL)
            
            if matches:
                letra_html = matches.group(1)
                letra = re.sub(r'<[^>]+>', '', letra_html)
                letra = letra.strip()
                
                if letra and len(letra) > 100:
                    return letra
        
        return None
        
    except Exception:
        return None

def buscar_letra(titulo, artista, spotify_id):
    """Busca letra em múltiplas fontes usando as informações exatas do Spotify."""
    
    # 1. Verifica cache primeiro
    cached_lyrics, source = get_cached_lyrics(spotify_id)
    if cached_lyrics:
        return cached_lyrics, "cache", "Letra em cache"
    
    # 2. Lista de fontes para tentar (em ordem de prioridade)
    fontes = [
        ("genius", buscar_letra_genius_direto),
        ("letrasemus", buscar_letra_letrasemus),
        ("vagalume", buscar_letra_vagalume),
        ("azlyrics", buscar_letra_azlyrics),
        ("lyricscom", buscar_letra_lyricscom),
    ]
    
    letras_encontradas = []
    
    for fonte_nome, funcao_busca in fontes:
        try:
            # Pula Genius se não tiver token
            if fonte_nome == "genius" and not GENIUS_ACCESS_TOKEN:
                continue
                
            letra = funcao_busca(titulo, artista)
            if letra and len(letra.strip()) > 150:  # Mínimo aumentado para 150 caracteres
                
                # Verificação de qualidade da letra
                linhas = letra.strip().split('\n')
                if len(linhas) < 3:
                    continue  # Muito curta, provavelmente não é uma letra completa
                
                # Verifica se não é uma página de erro ou busca
                palavras_erro = ["página não encontrada", "404", "not found", "buscar", "search", "resultados"]
                if any(palavra in letra.lower() for palavra in palavras_erro):
                    continue
                
                letras_encontradas.append({
                    "letra": letra.strip(),
                    "fonte": fonte_nome,
                    "tamanho": len(letra.strip()),
                    "linhas": len(linhas)
                })
                
                # Se encontrou uma letra boa de fonte confiável, salva e pode parar
                if fonte_nome in ["genius", "letrasemus"] and len(letra.strip()) > 300:
                    save_to_cache(spotify_id, titulo, artista, letra.strip(), fonte_nome)
                    return letra.strip(), fonte_nome, f"Letra encontrada via {fonte_nome}"
                
        except Exception as e:
            print(f"Erro na fonte {fonte_nome}: {e}")
            continue
    
    # 3. Escolhe a melhor letra (mais longa e com mais linhas)
    if letras_encontradas:
        # Prioriza letras mais longas e com mais linhas
        letras_encontradas.sort(key=lambda x: (x["tamanho"], x["linhas"]), reverse=True)
        melhor = letras_encontradas[0]
        
        # Salva no cache
        save_to_cache(spotify_id, titulo, artista, melhor["letra"], melhor["fonte"])
        
        return melhor["letra"], melhor["fonte"], f"Letra encontrada via {melhor['fonte']}"
    
    # 4. Se não encontrou nenhuma
    return None, None, "Nenhuma letra encontrada nas fontes disponíveis"

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

# Input
pedido = st.text_input(
    "🔍 Buscar música:",
    placeholder="Ex: Mas Você Que Eu Amo - Franco",
    help="Digite título e artista"
)

col1, col2 = st.columns([3, 1])
with col1:
    buscar_btn = st.button("🎵 Buscar e Analisar", type="primary", use_container_width=True)
with col2:
    if st.button("🔄 Limpar", use_container_width=True):
        st.rerun()

if buscar_btn and pedido:
    
    with st.spinner("Buscando no Spotify..."):
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
            
            if musica["explicit"]:
                st.error("⚠️ **CONTEÚDO EXPLÍCITO**")
            else:
                st.success("✅ Conteúdo Normal")
            
            if musica["preview_url"]:
                st.audio(musica["preview_url"], format="audio/mp3")
        
        # Busca letra
        st.subheader("📝 Buscando Letra")
        
        with st.spinner("Procurando letra em várias fontes..."):
            letra, fonte, status = buscar_letra(
                musica["titulo"],
                musica["artista_principal"],
                musica["id"]
            )
        
        if letra:
            st.success(f"✅ {status}")
            
            # Mostra um trecho da letra
            with st.expander("📜 Ver letra completa"):
                # Formata melhor a letra para exibição
                letra_formatada = letra.replace('\n\n', '\n\n')
                st.text_area("", letra_formatada, height=300)
        else:
            st.warning(f"⚠️ {status}")
            st.info("A análise será feita sem a letra da música.")
        
        # Análise
        st.subheader("🤖 Análise para Escola")
        
        with st.spinner("Analisando adequação..."):
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
            
            # Botão para adicionar
            if st.button("➕ Adicionar à Playlist da Festa", type="primary"):
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
st.caption("🔄 Cache de letras ativado | 🔐 Seguro | 🎯 Preciso")

# Estatísticas do cache
conn = sqlite3.connect('lyrics_cache.db')
c = conn.cursor()
c.execute('SELECT COUNT(*) FROM lyrics')
total_cache = c.fetchone()[0]
conn.close()

st.sidebar.title("📊 Estatísticas")
st.sidebar.metric("Letras em cache", total_cache)

# Testes rápidos
st.sidebar.title("🧪 Testes Rápidos")
test_musicas = [
    "Bohemian Rhapsody - Queen",
    "Blinding Lights - The Weeknd",
    "Mas Você Que Eu Amo - Franco",
    "Dance Monkey - Tones and I"
]

for test in test_musicas:
    if st.sidebar.button(f"Testar: {test.split('-')[0].strip()}"):
        st.session_state.test_input = test
        st.rerun()

if 'test_input' in st.session_state:
    pedido = st.session_state.test_input
    buscar_btn = True