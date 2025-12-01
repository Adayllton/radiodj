import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import google.generativeai as genai
import json
import os
from lyricsgenius import Genius
import requests
import re
from urllib.parse import quote

# --- CONFIGURAÇÕES ---
SPOTIFY_PLAYLIST_ID = st.secrets.get("SPOTIFY_PLAYLIST_ID") or os.getenv("SPOTIFY_PLAYLIST_ID")

# chaves / tokens vêm de secrets ou variáveis de ambiente
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
GENIUS_ACCESS_TOKEN = st.secrets.get("GENIUS_ACCESS_TOKEN") or os.getenv("GENIUS_ACCESS_TOKEN")

SPOTIFY_CLIENT_ID = st.secrets.get("SPOTIFY_CLIENT_ID") or os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = st.secrets.get("SPOTIFY_CLIENT_SECRET") or os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = st.secrets.get("SPOTIFY_REDIRECT_URI") or os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")

# Configuração da Página
st.set_page_config(page_title="DJ IA - Pedidos (Spotify)", page_icon="🎵")

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
            # Se não tem token cacheado, tenta renovar
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

@st.cache_resource
def setup_genius():
    """Inicializa o cliente Genius para busca de letras na web."""
    if not GENIUS_ACCESS_TOKEN:
        return None, "GENIUS_ACCESS_TOKEN não configurada (busca web desativada)."
    try:
        genius = Genius(
            GENIUS_ACCESS_TOKEN,
            skip_non_songs=True,
            excluded_terms=["(Remix)", "(Live)"],
            remove_section_headers=True,
            timeout=10,
            retries=2,
            sleep_time=3
        )
        genius.verbose = False
        genius._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        })
        return genius, None
    except Exception as e:
        return None, f"Erro ao configurar Genius: {e}"

model, sp, erro_setup = setup_apis()
genius, erro_genius = setup_genius()

# --- FUNÇÕES DE BUSCA DE LETRAS (MÚLTIPLAS FONTES) ---

def limpar_nome_artista(artista: str) -> str:
    """Limpa o nome do artista removendo featured, com, etc."""
    if not artista:
        return ""
    
    # Remove tudo depois de vírgulas, &, feat., com, etc.
    artista = artista.split(',')[0].split('&')[0].split('feat.')[0].split('ft.')[0].split('com')[0].split('with')[0]
    
    # Remove parênteses e seu conteúdo
    artista = re.sub(r'\([^)]*\)', '', artista)
    
    # Remove espaços extras
    artista = artista.strip()
    
    return artista

def obter_letra_vagalume(titulo: str, artista: str):
    """Fonte PRINCIPAL: API do Vagalume (excelente para músicas BR)."""
    try:
        artista_limpo = limpar_nome_artista(artista)
        
        if not artista_limpo or not titulo:
            return None
            
        # URL da API do Vagalume
        url = "https://api.vagalume.com.br/search.php"
        params = {
            "art": artista_limpo,
            "mus": titulo,
            "apikey": "free",  # API key gratuita
            "limit": 1
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Verifica se há resultados
            if "mus" in data and len(data["mus"]) > 0:
                letra = data["mus"][0].get("text", "")
                if letra and letra.strip():
                    return letra.strip()
        
        return None
        
    except Exception as e:
        return None

def obter_letra_letras_mus_br(titulo: str, artista: str):
    """Fonte alternativa: letras.mus.br (web scraping)."""
    try:
        artista_limpo = limpar_nome_artista(artista).lower().replace(' ', '-').replace("'", "")
        titulo_limpo = titulo.lower().replace(' ', '-').replace("'", "")
        
        # Tenta construir a URL padrão
        url = f"https://www.letras.mus.br/{artista_limpo}/{titulo_limpo}/"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            # Procura a letra usando regex (mais simples que BeautifulSoup)
            content = response.text
            
            # Procura pelo padrão comum das letras
            patterns = [
                r'<div[^>]*class="cnt-letra[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="lyric-original[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*itemprop="description"[^>]*>(.*?)</div>',
            ]
            
            for pattern in patterns:
                matches = re.search(pattern, content, re.DOTALL)
                if matches:
                    letra_html = matches.group(1)
                    # Remove tags HTML
                    letra = re.sub(r'<[^>]+>', '\n', letra_html)
                    letra = re.sub(r'\n\s*\n', '\n', letra)  # Remove linhas vazias extras
                    letra = letra.strip()
                    
                    if letra and len(letra) > 50:  # Verifica se tem conteúdo suficiente
                        return letra
        
        return None
        
    except Exception:
        return None

def obter_letra_genius(titulo: str, artista: str):
    """Fonte alternativa: Genius (pode estar bloqueada)."""
    if genius is None:
        return None

    try:
        artista_principal = limpar_nome_artista(artista)
        
        if artista_principal:
            song = genius.search_song(titulo, artista_principal)
        else:
            song = genius.search_song(titulo)

        # Fallback: busca apenas com título
        if song is None:
            query = f"{titulo} {artista_principal or ''}".strip()
            song = genius.search_song(query)

        if song and song.lyrics:
            return song.lyrics

    except Exception:
        return None

def obter_letra_lyrics_ovh(titulo: str, artista: str):
    """Fonte alternativa: API lyrics.ovh (simples e gratuita)."""
    try:
        artista_limpo = limpar_nome_artista(artista)
        
        if not artista_limpo:
            return None
            
        # URL encode os parâmetros
        artista_encoded = quote(artista_limpo)
        titulo_encoded = quote(titulo)
        
        url = f"https://api.lyrics.ovh/v1/{artista_encoded}/{titulo_encoded}"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            letra = data.get("lyrics", "")
            if letra and letra.strip():
                return letra.strip()
                
    except Exception:
        return None
    
    return None

def obter_letra(titulo: str, artista: str):
    """
    Busca letra em MÚLTIPLAS fontes na ordem de prioridade:
    1. Vagalume (melhor para BR)
    2. Lyrics.ovh (API simples)
    3. Genius (se disponível)
    4. Letras.mus.br (fallback)
    """
    fontes = [
        ("vagalume", obter_letra_vagalume),
        ("lyrics.ovh", obter_letra_lyrics_ovh),
        ("genius", obter_letra_genius),
        ("letras.mus.br", obter_letra_letras_mus_br),
    ]
    
    for nome_fonte, funcao_busca in fontes:
        try:
            letra = funcao_busca(titulo, artista)
            if letra:
                # Verifica se a letra tem conteúdo válido
                if len(letra.strip()) > 50:  # Pelo menos 50 caracteres
                    return letra, nome_fonte
        except Exception:
            continue
    
    return None, None

# --- FUNÇÕES RESTANTES (MANTIDAS) ---

def analisar_com_ia(titulo, artista, is_explicit, letra=None):
    # limita o tamanho da letra só por segurança
    letra_limpa = (
        letra
        or "NÃO FOI POSSÍVEL OBTER A LETRA. Use apenas título, artista e tag explícita."
    ).strip()
    
    # Remove linhas muito longas que podem quebrar o prompt
    letra_limpa = '\n'.join([linha[:200] + '...' if len(linha) > 200 else linha for linha in letra_limpa.split('\n')])
    
    if len(letra_limpa) > 6000:
        letra_limpa = letra_limpa[:6000] + "\n\n[trecho final omitido por tamanho]"

    prompt = f"""
    Você é um avaliador de músicas para tocarem em uma ESCOLA, com crianças e adolescentes
    (fundamental II / médio). Seu trabalho é decidir se a música é adequada em português, se for inglês tudo bem.

    Dados da música:
    - Título: {titulo}
    - Artista(s): {artista}
    - Tag explícita do Spotify: {"Sim" if is_explicit else "Não"}

    LETRA COMPLETA (ou mensagem de erro, se não encontrada):
    \"\"\"{letra_limpa}\"\"\"

    REGRAS (muito importantes):

    1. PROIBIDO NA ESCOLA (deve resultar em "aprovado": false):
       - Descrição EXPLÍCITA de ato sexual, genitália, pornografia ou fetiche.
       - Muitas referências a drogas ilícitas, crime, armas ou violência grave
         (matar, torturar, estupro etc.).
       - Apologia clara ao uso pesado de álcool/drogas.
       - Discurso de ódio, racismo, homofobia, machismo extremo ou xingamentos
         direcionados a grupos.

    2. PODE TOCAR (pode ser "aprovado": true):
       - Músicas românticas, dançantes, pop, rock, funk ou rap com teor leve.
       - Alguns poucos palavrões leves ou termos ambíguos, DESDE QUE não sejam o foco.
       - Insinuações românticas ou flerte sem descrever ato sexual de forma explícita.

    3. EQUILÍBRIO:
       - Se tiver UMA ou poucas palavrinhas "feias" mas o resto da letra é ok,
         deixe passar (aprovado: true) e explique que é leve.
       - Se a letra inteira gira em torno de sexo explícito, violência pesada,
         crime ou drogas, NÃO pode tocar (aprovado: false).
       - Se NÃO houver letra disponível, use o melhor julgamento com base em título,
         artista e tag explícita, mas NÃO bloqueie tudo automaticamente.

    Saída:
    Responda EXCLUSIVAMENTE com um JSON VÁLIDO, neste formato:

    {{
      "aprovado": true/false,
      "motivo": "explique em UMA frase simples por que pode ou não pode tocar na escola"
    }}
    """

    try:
        response = model.generate_content(prompt)

        if not hasattr(response, "text") or not response.text:
            raise ValueError("Resposta vazia da IA")

        texto = response.text.strip()
        texto = texto.replace("```json", "").replace("```", "").strip()

        inicio = texto.find("{")
        fim = texto.rfind("}")
        if inicio == -1 or fim == -1:
            raise ValueError(f"Resposta sem JSON válido: {texto}")

        json_str = texto[inicio:fim + 1]
        return json.loads(json_str)

    except Exception as e:
        st.error(f"Erro na IA: {e}")
        return {"aprovado": False, "motivo": "Erro na análise da IA"}

def buscar_musica_spotify(termo):
    """Busca música no Spotify."""
    if sp is None:
        st.error("Spotify não está configurado.")
        return None

    try:
        resultados = sp.search(q=termo, type="track", limit=5)
        items = resultados["tracks"]["items"]
        
        if not items:
            return None

        # Pega o primeiro resultado
        track = items[0]
        
        # Extrai informações
        track_info = {
            "id": track["id"],
            "titulo": track["name"],
            "artistas": ", ".join([artista["name"] for artista in track["artists"]]),
            "capa": track["album"]["images"][0]["url"] if track["album"]["images"] else None,
            "explicit": track["explicit"],
            "preview_url": track.get("preview_url"),
            "duration_ms": track["duration_ms"]
        }
        
        return track_info

    except Exception as e:
        st.error(f"Erro na busca no Spotify: {e}")
        return None

def adicionar_na_playlist_spotify(track_id):
    """Adiciona música à playlist do Spotify."""
    if sp is None:
        st.error("Spotify não está configurado.")
        return False

    try:
        # Verifica se a música já está na playlist
        playlist_tracks = sp.playlist_tracks(SPOTIFY_PLAYLIST_ID, fields="items(track(id))")
        existing_tracks = [item["track"]["id"] for item in playlist_tracks["items"]]
        
        if track_id in existing_tracks:
            return "DUPLICATE"
        
        # Adiciona à playlist
        sp.playlist_add_items(SPOTIFY_PLAYLIST_ID, [track_id])
        return "SUCCESS"
        
    except Exception as e:
        st.error(f"Erro ao adicionar na playlist do Spotify: {e}")
        return "ERROR"

# --- INTERFACE (FRONT-END) ---

st.title("🎧 DJ IA: Pedidos (Spotify Edition)")
st.write(
    "A IA analisará a LETRA da música (via múltiplas fontes) para ver se é adequada "
    "para tocar em ambiente escolar."
)

if erro_setup:
    st.error(f"Erro de configuração principal: {erro_setup}")
if erro_genius:
    st.info(erro_genius)

# Explicação sobre as fontes de letras
with st.expander("ℹ️ Sobre as fontes de letras"):
    st.write("""
    **Fontes utilizadas (na ordem de tentativa):**
    
    1. **Vagalume** - API oficial brasileira (melhor para músicas BR)
    2. **Lyrics.ovh** - API internacional gratuita
    3. **Genius** - Se disponível (pode estar temporariamente bloqueada)
    4. **Letras.mus.br** - Site brasileiro como fallback
    
    O sistema tenta automaticamente todas as fontes até encontrar a letra.
    """)

pedido = st.text_input(
    "Nome da música ou artista",
    placeholder="Ex: Bohemian Rhapsody - Queen",
)
botao_enviar = st.button("Enviar Pedido", type="primary")

if botao_enviar and pedido:
    if erro_setup:
        st.error("Não é possível processar pedidos enquanto houver erro de configuração nas APIs.")
    else:
        with st.spinner('🔍 Buscando no Spotify...'):
            musica = buscar_musica_spotify(pedido)

        if musica:
            # Extraindo dados
            titulo = musica["titulo"]
            artistas = musica["artistas"]
            capa = musica["capa"]
            track_id = musica["id"]
            is_explicit = musica["explicit"]

            col1, col2 = st.columns([1, 3])
            with col1:
                if capa:
                    st.image(capa, width=100)
            with col2:
                st.subheader(titulo)
                st.write(f"👤 {artistas}")
                if is_explicit:
                    st.caption("⚠️ Marcada como 'Explícita' no Spotify")
                if musica.get("preview_url"):
                    st.audio(musica["preview_url"], format="audio/mp3")

            # Buscar letra (múltiplas fontes)
            with st.spinner("📝 Buscando a letra da música em múltiplas fontes..."):
                letra, fonte = obter_letra(titulo, artistas)
                if letra:
                    # Exibe qual fonte encontrou a letra
                    fonte_nome = {
                        "vagalume": "Vagalume",
                        "lyrics.ovh": "Lyrics.ovh", 
                        "genius": "Genius",
                        "letras.mus.br": "Letras.mus.br"
                    }.get(fonte, fonte)
                    
                    st.success(f"✅ Letra encontrada via {fonte_nome}.")
                    with st.expander("📜 Ver letra da música"):
                        st.text_area("Letra:", letra, height=300)
                else:
                    st.info(
                        "Não encontrei a letra dessa música em nenhuma fonte. "
                        "Vou decidir só com título + artista + tag explícita."
                    )

            # Análise da IA
            with st.spinner('🤖 A IA está analisando a letra para ambiente escolar...'):
                decisao = analisar_com_ia(titulo, artistas, is_explicit, letra)

            if decisao.get("aprovado"):
                resultado = adicionar_na_playlist_spotify(track_id)
                
                if resultado == "SUCCESS":
                    st.success("✅ APROVADO! Adicionado à playlist da festa da escola.")
                    st.balloons()
                elif resultado == "DUPLICATE":
                    st.info("ℹ️ A música já estava na playlist, então não foi adicionada de novo.")
                else:
                    st.error("Erro ao adicionar na playlist do Spotify.")
                    
                st.caption(f"**Motivo da aprovação:** {decisao.get('motivo', 'Sem motivo informado')}")
            else:
                st.error("🚫 RECUSADO PARA AMBIENTE ESCOLAR")
                st.warning(f"**Motivo:** {decisao.get('motivo', 'Sem motivo informado')}")
        else:
            st.warning("Música não encontrada no Spotify. Tente ser mais específico.")

st.divider()
st.caption("🎵 Desenvolvido com Python, Streamlit, Spotipy, Gemini e múltiplas fontes de letras (modo Escola 🏫)")