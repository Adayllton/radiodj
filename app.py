import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import google.generativeai as genai
import json
import os
import requests
import re

# --- CONFIGURAÇÕES ---
SPOTIFY_PLAYLIST_ID = st.secrets.get("SPOTIFY_PLAYLIST_ID") or os.getenv("SPOTIFY_PLAYLIST_ID")

# chaves / tokens vêm de secrets ou variáveis de ambiente
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

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

# --- FUNÇÕES DE BUSCA DE MÚSICA (SPOTIFY) ---

def buscar_musica_spotify(termo):
    """Busca música no Spotify com precisão."""
    if sp is None:
        st.error("Spotify não está configurado.")
        return None

    try:
        # Busca com filtro para músicas
        resultados = sp.search(q=termo, type="track", limit=3, market="BR")
        items = resultados["tracks"]["items"]
        
        if not items:
            st.info("Nenhuma música encontrada no Spotify.")
            return None

        # Escolhe o resultado mais popular (ou o primeiro)
        track = items[0]
        
        # Retorna apenas os dados essenciais e precisos
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

# --- FUNÇÕES DE BUSCA DE LETRAS (PRECISAS E SIMPLES) ---

def limpar_texto(texto):
    """Limpa texto para busca."""
    if not texto:
        return ""
    
    # Remove parênteses e seu conteúdo
    texto = re.sub(r'\([^)]*\)', '', texto)
    
    # Remove colchetes e seu conteúdo
    texto = re.sub(r'\[[^\]]*\]', '', texto)
    
    # Remove caracteres especiais
    texto = re.sub(r'[^\w\sàáâãèéêìíîòóôõùúûçÀÁÂÃÈÉÊÌÍÎÒÓÔÕÙÚÛÇ\-\']', ' ', texto)
    
    # Remove espaços extras
    texto = re.sub(r'\s+', ' ', texto)
    
    return texto.strip()

def buscar_letra_vagalume(titulo, artista):
    """Busca letra no Vagalume - API brasileira precisa."""
    try:
        # Limpa os textos
        titulo_limpo = limpar_texto(titulo)
        artista_limpo = limpar_texto(artista)
        
        if not titulo_limpo or not artista_limpo:
            return None
        
        # URL da API do Vagalume
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
            
            # Verifica se há resultados
            if "mus" in data and len(data["mus"]) > 0:
                letra = data["mus"][0].get("text", "")
                if letra and len(letra.strip()) > 100:  # Verifica se tem conteúdo real
                    return letra.strip()
        
        return None
        
    except Exception as e:
        print(f"Erro Vagalume: {e}")
        return None

def buscar_letra_lyrics_ovh(titulo, artista):
    """Busca letra no lyrics.ovh - API internacional simples."""
    try:
        titulo_limpo = limpar_texto(titulo)
        artista_limpo = limpar_texto(artista)
        
        if not titulo_limpo or not artista_limpo:
            return None
        
        # Codifica os parâmetros para URL
        from urllib.parse import quote
        artista_encoded = quote(artista_limpo)
        titulo_encoded = quote(titulo_limpo)
        
        url = f"https://api.lyrics.ovh/v1/{artista_encoded}/{titulo_encoded}"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            letra = data.get("lyrics", "")
            if letra and len(letra.strip()) > 100:
                return letra.strip()
                
    except Exception as e:
        print(f"Erro lyrics.ovh: {e}")
        return None
    
    return None

def buscar_letra_combinacao_spotify(titulo, artista):
    """Tenta combinações diferentes para encontrar a letra correta."""
    
    # Lista de combinações a tentar (em ordem de prioridade)
    combinacoes = [
        # Combinação 1: Título e artista originais
        {"titulo": titulo, "artista": artista, "desc": "Originais"},
        
        # Combinação 2: Título limpo e artista limpo
        {"titulo": limpar_texto(titulo), "artista": limpar_texto(artista), "desc": "Limpos"},
        
        # Combinação 3: Apenas artista principal (se tiver vários)
        {"titulo": titulo, "artista": artista.split(",")[0].split("&")[0].strip(), "desc": "Artista principal"},
        
        # Combinação 4: Título sem "feat." e artista principal
        {"titulo": re.sub(r'\s*\(.*?\)', '', titulo), 
         "artista": artista.split(",")[0].split("&")[0].strip(), 
         "desc": "Sem parênteses"},
    ]
    
    for combo in combinacoes:
        if not combo["titulo"] or not combo["artista"]:
            continue
            
        # Tenta Vagalume primeiro (melhor para BR)
        letra = buscar_letra_vagalume(combo["titulo"], combo["artista"])
        if letra:
            return letra, "vagalume", combo["desc"]
        
        # Tenta lyrics.ovh como fallback
        letra = buscar_letra_lyrics_ovh(combo["titulo"], combo["artista"])
        if letra:
            return letra, "lyrics.ovh", combo["desc"]
    
    return None, None, None

# --- FUNÇÕES DE ANÁLISE ---

def analisar_com_ia(titulo, artista, is_explicit, letra=None):
    """Analisa a música com IA de forma simples e precisa."""
    
    # Prepara a letra para análise
    if letra:
        letra_limpa = letra.strip()
        # Limita o tamanho para evitar problemas
        if len(letra_limpa) > 4000:
            letra_limpa = letra_limpa[:4000] + "... [continua]"
    else:
        letra_limpa = "LETRA NÃO ENCONTRADA. Decida baseado apenas no título, artista e tag explícita."
    
    prompt = f"""
    Você é um avaliador de músicas para tocarem em uma ESCOLA, com crianças e adolescentes
    (fundamental II / médio), mas só as brasileiras. Seu trabalho é decidir se a música é adequada em português, se for inglês tudo bem, pode passar, ou em espanhol, so veirifoca se tem algo pesado no sentido de gore ou violência, mas questões como ser vulgar não tem problema em outra língua, pode passar.

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
       - Se for inglês pode até ser bem mais explícita, apenas não justifique a aprovação.

    Saída:
    Responda EXCLUSIVAMENTE com um JSON VÁLIDO, neste formato:

    {{
      "aprovado": true/false,
      "motivo": "explique em UMA frase simples por que pode ou não pode tocar na escola"
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        
        if not response.text:
            return {"aprovado": False, "motivo": "Erro na análise"}
        
        # Extrai o JSON da resposta
        texto = response.text.strip()
        
        # Remove markdown code blocks se existirem
        texto = texto.replace("```json", "").replace("```", "").strip()
        
        # Procura por JSON
        inicio = texto.find("{")
        fim = texto.rfind("}")
        
        if inicio != -1 and fim != -1:
            json_str = texto[inicio:fim+1]
            return json.loads(json_str)
        else:
            # Fallback: tenta interpretar como texto simples
            if "aprovado" in texto.lower() and "true" in texto.lower():
                return {"aprovado": True, "motivo": "Aprovado pela IA"}
            else:
                return {"aprovado": False, "motivo": "Reprovado pela IA"}
                
    except Exception as e:
        return {"aprovado": False, "motivo": f"Erro técnico: {str(e)}"}

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
        st.error(f"Erro ao adicionar na playlist: {e}")
        return "ERROR"

# --- INTERFACE PRINCIPAL ---

st.title("🎧 DJ IA - Sistema Escolar")
st.write("Analise músicas para tocar em ambiente escolar")

if erro_setup:
    st.error(f"Erro de configuração: {erro_setup}")

# Input do usuário
pedido = st.text_input(
    "Digite o nome da música ou artista:",
    placeholder="Ex: Mas Você Que Eu Amo - Franco",
    help="Você pode digitar apenas o nome da música, apenas o artista, ou ambos"
)

# Botão de busca
if st.button("🔍 Buscar e Analisar", type="primary") and pedido:
    
    with st.spinner("Buscando música no Spotify..."):
        musica = buscar_musica_spotify(pedido)
    
    if musica:
        # Exibe informações da música
        st.subheader("🎵 Música Encontrada")
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            if musica["capa"]:
                st.image(musica["capa"], width=150)
        
        with col2:
            st.write(f"**Título:** {musica['titulo']}")
            st.write(f"**Artista(s):** {musica['artistas_completos']}")
            st.write(f"**Álbum:** {musica['album']}")
            st.write(f"**Popularidade:** {musica['popularidade']}/100")
            
            if musica["explicit"]:
                st.warning("⚠️ **Conteúdo Explícito**")
            else:
                st.info("✅ Conteúdo Normal")
            
            if musica["preview_url"]:
                st.audio(musica["preview_url"])
        
        # Busca a letra
        st.subheader("📝 Buscando Letra")
        
        with st.spinner("Procurando letra precisa..."):
            letra, fonte, combo = buscar_letra_combinacao_spotify(
                musica["titulo"], 
                musica["artista_principal"]
            )
        
        if letra:
            st.success(f"✅ Letra encontrada ({fonte})")
            
            # Mostra trecho da letra
            with st.expander("Ver letra completa"):
                st.text_area("", letra, height=300, disabled=True)
        else:
            st.warning("Não foi possível encontrar a letra exata desta música")
            letra = None
        
        # Análise da IA
        st.subheader("🤖 Análise para Escola")
        
        with st.spinner("Analisando adequação..."):
            decisao = analisar_com_ia(
                musica["titulo"],
                musica["artistas_completos"],
                musica["explicit"],
                letra
            )
        
        # Mostra resultado
        if decisao.get("aprovado"):
            st.success("✅ **APROVADA PARA A ESCOLA**")
            st.balloons()
            
            # Tenta adicionar à playlist
            resultado = adicionar_na_playlist_spotify(musica["id"])
            
            if resultado == "SUCCESS":
                st.success("🎵 Adicionada à playlist da festa!")
            elif resultado == "DUPLICATE":
                st.info("ℹ️ Esta música já está na playlist")
            else:
                st.error("❌ Erro ao adicionar à playlist")
            
            st.write(f"**Motivo:** {decisao.get('motivo', 'Sem motivo especificado')}")
        
        else:
            st.error("❌ **NÃO APROVADA PARA A ESCOLA**")
            st.write(f"**Motivo:** {decisao.get('motivo', 'Sem motivo especificado')}")
    
    else:
        st.error("Não encontrei essa música no Spotify. Tente ser mais específico.")

# Informações no rodapé
st.divider()
st.caption("🎶 Sistema de análise musical para ambiente escolar")
st.caption("🔄 Atualizações automáticas | 🔐 Seguro | 🎯 Preciso")

# Adiciona algumas dicas
with st.expander("💡 Dicas para busca precisa"):
    st.write("""
    1. **Para músicas brasileiras:** Funciona melhor!
    2. **Formato ideal:** "Nome da música - Artista"
    3. **Exemplos que funcionam bem:**
       - "Mas Você Que Eu Amo - Franco"
       - "Bohemian Rhapsody - Queen"
       - "Blinding Lights - The Weeknd"
    4. **Fontes de letras:** Vagalume (BR) e lyrics.ovh (internacional)
    """)