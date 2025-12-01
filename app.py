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
        resultados = sp.search(q=termo, type="track", limit=5, market="BR")
        items = resultados["tracks"]["items"]
        
        if not items:
            return None

        # Escolhe o resultado mais relevante (primeiro)
        track = items[0]
        
        return {
            "id": track["id"],
            "titulo": track["name"],
            "artista_principal": track["artists"][0]["name"] if track["artists"] else "",
            "artistas_completos": ", ".join([a["name"] for a in track["artists"]]),
            "capa": track["album"]["images"][0]["url"] if track["album"]["images"] else None,
            "explicit": track["explicit"],
            "preview_url": track.get("preview_url"),
            "album": track["album"]["name"],
            "popularidade": track.get("popularity", 0),
        }

    except Exception as e:
        st.error(f"Erro na busca do Spotify: {e}")
        return None

# --- FUNÇÕES DE BUSCA DE LETRAS (AGORA FUNCIONANDO!) ---

def buscar_letra_genius_direto(titulo, artista):
    """Busca letra no Genius usando requisição direta com token."""
    if not GENIUS_ACCESS_TOKEN:
        return None
        
    try:
        # Limpa o texto
        titulo_limpo = re.sub(r'[^\w\s\-]', '', titulo)
        artista_limpo = artista.split(",")[0].split("&")[0].split("feat.")[0].strip()
        
        # Busca no Genius API
        headers = {
            'Authorization': f'Bearer {GENIUS_ACCESS_TOKEN}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Primeiro busca a música
        search_url = "https://api.genius.com/search"
        params = {
            'q': f"{titulo_limpo} {artista_limpo}",
            'per_page': 5
        }
        
        response = requests.get(search_url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('response') and data['response'].get('hits'):
                # Pega o primeiro hit
                hit = data['response']['hits'][0]['result']
                
                # Agora busca a letra da música
                song_url = f"https://api.genius.com/songs/{hit['id']}"
                song_response = requests.get(song_url, headers=headers, timeout=15)
                
                if song_response.status_code == 200:
                    song_data = song_response.json()
                    
                    # Tenta obter a letra da estrutura da API
                    if 'song' in song_data and 'lyrics' in song_data['song']:
                        return song_data['song']['lyrics']['plain']
                        
        return None
        
    except Exception as e:
        print(f"Erro Genius direto: {e}")
        return None

def buscar_letra_letrasemus(titulo, artista):
    """Busca letra no site letras.mus.br."""
    try:
        # Limpa o texto para URL
        artista_limpo = artista.split(",")[0].split("&")[0].split("feat.")[0].strip().lower()
        titulo_limpo = titulo.lower()
        
        # Remove caracteres especiais e espaços
        import urllib.parse
        artista_url = urllib.parse.quote_plus(artista_limpo.replace(' ', '-'))
        titulo_url = urllib.parse.quote_plus(titulo_limpo.replace(' ', '-'))
        
        # Formata a URL do letras.mus.br
        url = f"https://www.letras.mus.br/{artista_url}/{titulo_url}/"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            content = response.text
            
            # Procura a div principal da letra
            import re
            
            # Padrão 1: div com classe "cnt-letra"
            pattern1 = r'<div class="cnt-letra[^"]*"[^>]*>(.*?)</div>'
            # Padrão 2: conteúdo dentro de tags <p> dentro da letra
            pattern2 = r'<p>(.*?)</p>'
            
            # Tenta encontrar usando o primeiro padrão
            matches = re.search(pattern1, content, re.DOTALL)
            if matches:
                letra_html = matches.group(1)
                
                # Extrai o texto das tags <p>
                paragraphs = re.findall(pattern2, letra_html, re.DOTALL)
                
                if paragraphs:
                    # Limpa cada parágrafo
                    letra_limpa = []
                    for p in paragraphs:
                        # Remove tags HTML
                        p_clean = re.sub(r'<[^>]+>', '', p)
                        # Substitui <br> por quebras de linha
                        p_clean = re.sub(r'<br\s*/?>', '\n', p_clean)
                        p_clean = p_clean.strip()
                        if p_clean:
                            letra_limpa.append(p_clean)
                    
                    letra_completa = '\n\n'.join(letra_limpa)
                    
                    # Remove múltiplas quebras de linha
                    letra_completa = re.sub(r'\n\s*\n', '\n\n', letra_completa)
                    
                    if letra_completa and len(letra_completa.strip()) > 100:
                        return letra_completa.strip()
            
            # Alternativa: buscar em outras partes da página
            pattern3 = r'<div class="lyric-original"[^>]*>(.*?)</div>'
            matches = re.search(pattern3, content, re.DOTALL)
            
            if matches:
                letra_html = matches.group(1)
                # Limpa tags HTML
                letra = re.sub(r'<[^>]+>', '', letra_html)
                letra = re.sub(r'\n\s*\n', '\n\n', letra)
                letra = letra.strip()
                
                if letra and len(letra) > 100:
                    return letra
        
        return None
        
    except Exception as e:
        print(f"Erro no letras.mus.br: {e}")
        return None

def buscar_letra_vagalume(titulo, artista):
    """Busca letra no Vagalume com fallbacks."""
    try:
        # Limpa o texto
        titulo_limpo = re.sub(r'[^\w\s\-]', '', titulo)
        artista_limpo = artista.split(",")[0].split("&")[0].split("feat.")[0].strip()
        
        # Primeira tentativa: busca direta
        url = "https://api.vagalume.com.br/search.php"
        params = {
            "art": artista_limpo,
            "mus": titulo_limpo,
            "apikey": "free",
            "limit": 1
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if "mus" in data and len(data["mus"]) > 0:
                letra = data["mus"][0].get("text", "")
                if letra and len(letra.strip()) > 50:
                    return letra.strip()
        
        # Segunda tentativa: busca apenas pelo artista
        params = {
            "art": artista_limpo,
            "apikey": "free",
            "limit": 10
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if "mus" in data and len(data["mus"]) > 0:
                # Procura por título similar
                for musica in data["mus"]:
                    if musica.get("name", "").lower() in titulo.lower() or titulo.lower() in musica.get("name", "").lower():
                        letra = musica.get("text", "")
                        if letra and len(letra.strip()) > 50:
                            return letra.strip()
        
        return None
        
    except Exception as e:
        print(f"Erro no Vagalume: {e}")
        return None

def buscar_letra_azlyrics(titulo, artista):
    """Busca no AZLyrics usando web scraping."""
    try:
        import urllib.parse
        
        # Prepara o artista e título para a URL
        # Remove caracteres especiais do artista
        artista_formatado = re.sub(r'[^\w\s-]', '', artista.lower())
        artista_formatado = re.sub(r'[\s&]+', '', artista_formatado)
        
        # Remove caracteres especiais do título
        titulo_formatado = re.sub(r'[^\w\s-]', '', titulo.lower())
        titulo_formatado = re.sub(r'[\s]+', '', titulo_formatado)
        
        # Substitui 'feat' e similares
        artista_formatado = re.sub(r'feat.*$', '', artista_formatado).strip()
        
        url = f"https://www.azlyrics.com/lyrics/{artista_formatado}/{titulo_formatado}.html"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.azlyrics.com/',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            content = response.text
            
            # Procura o comentário específico que marca o início da letra
            start_marker = '<!-- Usage of azlyrics.com content by any third-party lyrics provider is prohibited by our licensing agreement. Sorry about that. -->'
            end_marker = '<!-- MxM banner -->'
            
            if start_marker in content:
                start_index = content.find(start_marker) + len(start_marker)
                
                # Encontra o fim da letra
                if end_marker in content[start_index:]:
                    end_index = content.find(end_marker, start_index)
                else:
                    # Fallback: procura pela próxima div em branco
                    end_index = content.find('</div>', start_index)
                
                if end_index > start_index:
                    letra_html = content[start_index:end_index]
                    
                    # Limpa as tags HTML e espaços extras
                    letra = re.sub(r'<[^>]+>', '', letra_html)
                    letra = re.sub(r'\n\s*\n', '\n', letra)
                    letra = letra.strip()
                    
                    if letra and len(letra) > 100:
                        return letra
        
        return None
        
    except Exception as e:
        print(f"Erro no AZLyrics: {e}")
        return None

def buscar_letra_spotify(titulo, artista):
    """Tenta obter letra usando a API do Spotify (requer subscription)."""
    # Esta função requer acesso premium à API do Spotify
    # Por enquanto vamos usar como placeholder
    return None

def buscar_letra(titulo, artista, spotify_id):
    """Busca letra em múltiplas fontes e retorna a melhor."""
    
    # 1. Verifica cache primeiro
    cached_lyrics, source = get_cached_lyrics(spotify_id)
    if cached_lyrics:
        return cached_lyrics, "cache", "Letra em cache"
    
    # 2. Lista de fontes para tentar (em ordem de prioridade)
    fontes = [
        ("genius", buscar_letra_genius_direto),
        ("letrasemus", buscar_letra_letrasemus),  # Adicionado aqui
        ("vagalume", buscar_letra_vagalume),
        ("azlyrics", buscar_letra_azlyrics),
    ]
    
    letras_encontradas = []
    
    for fonte_nome, funcao_busca in fontes:
        try:
            letra = funcao_busca(titulo, artista)
            if letra and len(letra.strip()) > 100:  # Mínimo de 100 caracteres
                letras_encontradas.append({
                    "letra": letra.strip(),
                    "fonte": fonte_nome,
                    "tamanho": len(letra.strip())
                })
                
                # Se encontrou uma letra boa, salva no cache
                save_to_cache(spotify_id, titulo, artista, letra.strip(), fonte_nome)
                
                # Se a fonte for confiável (genius, letrasemus), podemos parar aqui
                if fonte_nome in ["genius", "letrasemus"] and len(letra.strip()) > 200:
                    break
                
        except Exception as e:
            print(f"Erro na fonte {fonte_nome}: {e}")
            continue
    
    # 3. Escolhe a melhor letra (mais longa)
    if letras_encontradas:
        letras_encontradas.sort(key=lambda x: x["tamanho"], reverse=True)
        melhor = letras_encontradas[0]
        return melhor["letra"], melhor["fonte"], f"Letra encontrada via {melhor['fonte']}"
    
    # 4. Se não encontrou nenhuma
    return None, None, "Nenhuma letra encontrada"

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
                st.text_area("", letra, height=300)
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