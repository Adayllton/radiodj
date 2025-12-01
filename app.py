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

# --- FUNÇÕES DE BUSCA DE MÚSICA (SPOTIFY) COM DADOS COMPLETOS ---

def buscar_musica_spotify(termo):
    """Busca música no Spotify e retorna TODOS os dados disponíveis."""
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
        
        # Extrai TODOS os dados relevantes
        track_info = {
            # IDENTIFICAÇÃO
            "id": track["id"],
            "uri": track["uri"],
            "spotify_url": track["external_urls"]["spotify"],
            
            # INFORMAÇÕES BÁSICAS
            "titulo": track["name"],
            "artistas_nomes": [artista["name"] for artista in track["artists"]],
            "artistas_ids": [artista["id"] for artista in track["artists"]],
            "artista_principal": track["artists"][0]["name"] if track["artists"] else "",
            "artistas_string": ", ".join([artista["name"] for artista in track["artists"]]),
            
            # ÁLBUM
            "album_nome": track["album"]["name"],
            "album_id": track["album"]["id"],
            "album_tipo": track["album"]["album_type"],
            "album_artistas": [artista["name"] for artista in track["album"]["artists"]],
            "data_lancamento": track["album"]["release_date"],
            "total_faixas": track["album"]["total_tracks"],
            
            # METADADOS
            "explicit": track["explicit"],
            "popularidade": track.get("popularity", 0),
            "numero_faixa": track.get("track_number", 1),
            "disco_numero": track.get("disc_number", 1),
            "duracao_ms": track["duration_ms"],
            "duracao_min": round(track["duration_ms"] / 60000, 2),
            
            # IMAGENS
            "capa_url": track["album"]["images"][0]["url"] if track["album"]["images"] else None,
            "capas": track["album"]["images"] if track["album"]["images"] else [],
            
            # EXTRAS
            "preview_url": track.get("preview_url"),
            "disponivel_mercados": track.get("available_markets", []),
            
            # TIMESTAMPS
            "adicionado_em": track.get("added_at"),
            "eh_local": track.get("is_local", False),
            
            # DADOS COMPLEMENTARES PARA BUSCA
            "dados_completos": track  # Mantém os dados brutos completos
        }
        
        return track_info

    except Exception as e:
        st.error(f"Erro na busca no Spotify: {e}")
        return None

# --- FUNÇÕES DE LIMPEZA E PREPARAÇÃO DE DADOS ---

def preparar_dados_para_busca(musica_info):
    """Prepara múltiplas variações dos dados para busca de letras."""
    titulo = musica_info["titulo"]
    artistas = musica_info["artistas_nomes"]
    artista_principal = musica_info["artista_principal"]
    album = musica_info["album_nome"]
    
    variacoes = []
    
    # Variação 1: Título original + todos artistas
    variacoes.append({
        "titulo": titulo,
        "artista": ", ".join(artistas),
        "descricao": "Título original + todos artistas"
    })
    
    # Variação 2: Título original + artista principal
    variacoes.append({
        "titulo": titulo,
        "artista": artista_principal,
        "descricao": "Título original + artista principal"
    })
    
    # Variação 3: Título limpo (sem parênteses) + artista principal
    titulo_limpo = re.sub(r'\([^)]*\)', '', titulo).strip()
    if titulo_limpo != titulo:
        variacoes.append({
            "titulo": titulo_limpo,
            "artista": artista_principal,
            "descricao": "Título limpo + artista principal"
        })
    
    # Variação 4: Título original + artista principal + álbum (para APIs que suportam)
    variacoes.append({
        "titulo": titulo,
        "artista": artista_principal,
        "album": album,
        "descricao": "Título + artista + álbum"
    })
    
    # Variação 5: Título em minúsculas + artista principal
    variacoes.append({
        "titulo": titulo.lower(),
        "artista": artista_principal.lower(),
        "descricao": "Tudo em minúsculas"
    })
    
    # Variação 6: Remover "feat.", "ft.", "com", etc.
    titulo_sem_feat = re.sub(r'\s*(feat\.|ft\.|com|with|&)\s*[^)]+', '', titulo, flags=re.IGNORECASE).strip()
    if titulo_sem_feat != titulo:
        variacoes.append({
            "titulo": titulo_sem_feat,
            "artista": artista_principal,
            "descricao": "Título sem 'feat.' + artista principal"
        })
    
    return variacoes

# --- FUNÇÕES DE BUSCA DE LETRAS (MÚLTIPLAS FONTES COM DADOS COMPLETOS) ---

def obter_letra_vagalume(titulo, artista, album=None):
    """Fonte PRINCIPAL: API do Vagalume."""
    try:
        # API do Vagalume aceita apenas artista e música
        url = "https://api.vagalume.com.br/search.php"
        params = {
            "art": artista,
            "mus": titulo,
            "apikey": "free",
            "limit": 1
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if "mus" in data and len(data["mus"]) > 0:
                letra = data["mus"][0].get("text", "")
                if letra and letra.strip():
                    return letra.strip()
        
        return None
        
    except Exception:
        return None

def obter_letra_lyrics_ovh(titulo, artista, album=None):
    """Fonte alternativa: API lyrics.ovh."""
    try:
        artista_encoded = quote(artista)
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

def obter_letra_genius(titulo, artista, album=None):
    """Fonte alternativa: Genius."""
    if genius is None:
        return None

    try:
        # Genius pode usar álbum para melhorar a busca
        query = f"{titulo} {artista}"
        if album:
            query = f"{titulo} {artista} {album}"
            
        song = genius.search_song(query)
        
        if song and song.lyrics:
            return song.lyrics

    except Exception:
        return None

def obter_letra_letras_mus_br(titulo, artista, album=None):
    """Fonte alternativa: letras.mus.br."""
    try:
        # Prepara URL amigável
        artista_limpo = artista.lower().replace(' ', '-').replace("'", "")
        titulo_limpo = titulo.lower().replace(' ', '-').replace("'", "")
        
        # Tenta várias variações de URL
        urls = [
            f"https://www.letras.mus.br/{artista_limpo}/{titulo_limpo}/",
            f"https://www.letras.mus.br/{artista_limpo.replace('-', '_')}/{titulo_limpo.replace('-', '_')}/",
        ]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        for url in urls:
            try:
                response = requests.get(url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    # Procura padrões comuns de letras
                    content = response.text
                    
                    patterns = [
                        r'<div[^>]*class="cnt-letra[^"]*"[^>]*>(.*?)</div>',
                        r'<div[^>]*class="lyric-original[^"]*"[^>]*>(.*?)</div>',
                        r'<div[^>]*itemprop="description"[^>]*>(.*?)</div>',
                    ]
                    
                    for pattern in patterns:
                        matches = re.search(pattern, content, re.DOTALL)
                        if matches:
                            letra_html = matches.group(1)
                            letra = re.sub(r'<[^>]+>', '\n', letra_html)
                            letra = re.sub(r'\n\s*\n', '\n', letra)
                            letra = letra.strip()
                            
                            if letra and len(letra) > 50:
                                return letra
            except:
                continue
        
        return None
        
    except Exception:
        return None

def buscar_letra_com_dados_completos(musica_info):
    """
    Busca letra usando TODOS os dados da música.
    Tenta múltiplas combinações e múltiplas fontes.
    """
    # Prepara todas as variações de busca
    variacoes = preparar_dados_para_busca(musica_info)
    
    fontes = [
        ("vagalume", obter_letra_vagalume),
        ("lyrics.ovh", obter_letra_lyrics_ovh),
        ("genius", obter_letra_genius),
        ("letras.mus.br", obter_letra_letras_mus_br),
    ]
    
    resultados_tentativas = []
    
    for variavel in variacoes:
        for nome_fonte, funcao_busca in fontes:
            try:
                letra = funcao_busca(
                    titulo=variavel["titulo"],
                    artista=variavel["artista"],
                    album=variavel.get("album")
                )
                
                if letra and len(letra.strip()) > 50:
                    resultados_tentativas.append({
                        "letra": letra.strip(),
                        "fonte": nome_fonte,
                        "variavel_usada": variavel["descricao"],
                        "titulo_usado": variavel["titulo"],
                        "artista_usado": variavel["artista"],
                        "comprimento": len(letra.strip())
                    })
                    
            except Exception:
                continue
    
    # Ordena por melhor resultado (maior comprimento de letra primeiro)
    if resultados_tentativas:
        resultados_tentativas.sort(key=lambda x: x["comprimento"], reverse=True)
        melhor_resultado = resultados_tentativas[0]
        return melhor_resultado["letra"], melhor_resultado["fonte"], melhor_resultado["variavel_usada"]
    
    return None, None, None

# --- FUNÇÕES DE ANÁLISE E ADIÇÃO À PLAYLIST ---

def analisar_com_ia(titulo, artista, is_explicit, letra=None):
    """Analisa a música com IA usando dados completos."""
    letra_limpa = (
        letra
        or "NÃO FOI POSSÍVEL OBTER A LETRA. Use apenas título, artista e tag explícita."
    ).strip()
    
    # Remove linhas muito longas
    letra_limpa = '\n'.join([linha[:200] + '...' if len(linha) > 200 else linha 
                            for linha in letra_limpa.split('\n')])
    
    if len(letra_limpa) > 6000:
        letra_limpa = letra_limpa[:6000] + "\n\n[trecho final omitido por tamanho]"

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

# Explicação sobre o sistema
with st.expander("ℹ️ Sobre o sistema"):
    st.write("""
    **Dados coletados do Spotify:**
    - Título da música
    - Todos os artistas envolvidos
    - Nome do álbum
    - Data de lançamento
    - Popularidade
    - Tag explícita
    - E muitos outros metadados
    
    **Busca de letras:**
    O sistema usa TODOS os dados disponíveis para buscar a letra correta em múltiplas fontes:
    1. Vagalume (API brasileira)
    2. Lyrics.ovh (API internacional)
    3. Genius
    4. Letras.mus.br
    
    **Processo:**
    - Coleta todos os dados do Spotify
    - Cria múltiplas variações de busca
    - Tenta todas as fontes com todas as variações
    - Seleciona a melhor letra encontrada
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
            # Exibe dados completos da música
            with st.expander("📊 Ver todos os dados da música"):
                st.json({k: v for k, v in musica.items() if k != "dados_completos"})
            
            # Extrai dados principais para exibição
            titulo = musica["titulo"]
            artistas = musica["artistas_string"]
            capa = musica["capa_url"]
            track_id = musica["id"]
            is_explicit = musica["explicit"]
            album = musica["album_nome"]
            lancamento = musica["data_lancamento"]
            popularidade = musica["popularidade"]

            col1, col2 = st.columns([1, 3])
            with col1:
                if capa:
                    st.image(capa, width=120)
            
            with col2:
                st.subheader(titulo)
                st.write(f"**👤 Artistas:** {artistas}")
                st.write(f"**💿 Álbum:** {album} ({lancamento})")
                st.write(f"**⭐ Popularidade:** {popularidade}/100")
                
                if is_explicit:
                    st.warning("⚠️ **Marcada como 'Explícita' no Spotify**")
                
                if musica.get("preview_url"):
                    st.audio(musica["preview_url"], format="audio/mp3")

            # Buscar letra com dados completos
            with st.spinner("📝 Buscando a letra com dados completos..."):
                letra, fonte, variavel_usada = buscar_letra_com_dados_completos(musica)
                
                if letra:
                    fonte_nome = {
                        "vagalume": "Vagalume",
                        "lyrics.ovh": "Lyrics.ovh", 
                        "genius": "Genius",
                        "letras.mus.br": "Letras.mus.br"
                    }.get(fonte, fonte)
                    
                    st.success(f"✅ Letra encontrada via **{fonte_nome}**")
                    st.info(f"🔍 Busca usou: *{variavel_usada}*")
                    
                    with st.expander("📜 Ver letra da música"):
                        st.text_area("Letra:", letra, height=300, key="letra_area")
                else:
                    st.warning(
                        "Não encontrei a letra dessa música em nenhuma fonte. "
                        "Vou decidir só com os metadados disponíveis."
                    )

            # Análise da IA
            with st.spinner('🤖 A IA está analisando para ambiente escolar...'):
                decisao = analisar_com_ia(titulo, artistas, is_explicit, letra)

            if decisao.get("aprovado"):
                resultado = adicionar_na_playlist_spotify(track_id)
                
                if resultado == "SUCCESS":
                    st.success("✅ **APROVADO!** Adicionado à playlist da festa da escola.")
                    st.balloons()
                elif resultado == "DUPLICATE":
                    st.info("ℹ️ A música já estava na playlist, então não foi adicionada de novo.")
                else:
                    st.error("Erro ao adicionar na playlist do Spotify.")
                    
                st.caption(f"**📝 Motivo da aprovação:** {decisao.get('motivo', 'Sem motivo informado')}")
            else:
                st.error("🚫 **RECUSADO PARA AMBIENTE ESCOLAR**")
                st.warning(f"**📝 Motivo:** {decisao.get('motivo', 'Sem motivo informado')}")
        else:
            st.warning("Música não encontrada no Spotify. Tente ser mais específico.")

st.divider()
st.caption("🎵 **Desenvolvido com Python, Streamlit, Spotipy, Gemini e múltiplas fontes de letras**")
st.caption("🏫 **Modo Escola - Análise de adequação para ambiente escolar**")