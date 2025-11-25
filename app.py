import streamlit as st
from ytmusicapi import YTMusic
import google.generativeai as genai
import json
import os
from lyricsgenius import Genius

# --- CONFIGURAÇÕES ---
# Recomendo fortemente usar variáveis de ambiente:
#   export GEMINI_API_KEY="sua_chave_aqui"
#   export GENIUS_ACCESS_TOKEN="seu_token_genius_aqui"
PLAYLIST_ID = "PL_45f9jLesgjdE5usz75-zDtBt7ChSM5f"  # sem &jct

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
GENIUS_ACCESS_TOKEN = st.secrets.get("GENIUS_ACCESS_TOKEN") or os.getenv("GENIUS_ACCESS_TOKEN")

OAUTH_JSON = st.secrets.get("OAUTH_JSON")
OAUTH_CREDENTIALS_JSON = st.secrets.get("OAUTH_CREDENTIALS_JSON")


# Configuração da Página
st.set_page_config(page_title="DJ IA - Pedidos", page_icon="🎵")

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

    # --- YTMusic via OAuth ---
    tokens = creds = None

    if OAUTH_JSON:
        try:
            tokens = json.loads(OAUTH_JSON)
        except Exception as e:
            return None, None, f"Erro ao ler OAUTH_JSON dos secrets: {e}"

    if OAUTH_CREDENTIALS_JSON:
        try:
            creds = json.loads(OAUTH_CREDENTIALS_JSON)
        except Exception as e:
            return None, None, f"Erro ao ler OAUTH_CREDENTIALS_JSON dos secrets: {e}"

    try:
        if tokens and creds:
            # usa OAuth completo (tokens + credenciais) em memória
            yt = YTMusic(auth=tokens, oauth_credentials=creds)
        else:
            # fallback local: só pra desenvolvimento na sua máquina
            if os.path.exists("oauth.json") and os.path.exists("oauth_credentials.json"):
                yt = YTMusic("oauth.json", oauth_credentials="oauth_credentials.json")
            else:
                return model, None, (
                    "Configuração OAuth do YTMusic não encontrada. "
                    "Defina OAUTH_JSON e OAUTH_CREDENTIALS_JSON nos secrets "
                    "ou deixe os arquivos oauth*.json na pasta."
                )

        return model, yt, None
    except Exception as e:
        return None, None, f"Erro ao configurar YTMusic: {e}"


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
        )
        genius.verbose = False
        return genius, None
    except Exception as e:
        return None, f"Erro ao configurar Genius: {e}"


model, yt, erro_setup = setup_apis()
genius, erro_genius = setup_genius()

# --- FUNÇÕES DE LÓGICA ---


def obter_letra_ytmusic(video_id: str):
    """Tenta obter a letra da música a partir do YouTube Music."""
    try:
        # 1) Algumas versões do ytmusicapi aceitam videoId direto
        try:
            dados = yt.get_lyrics(video_id)
            if dados and dados.get("lyrics"):
                return dados["lyrics"]
        except Exception:
            pass  # se falhar, tenta o fluxo "oficial"

        # 2) Fluxo documentado: get_watch_playlist -> lyrics.browseId -> get_lyrics
        watch = yt.get_watch_playlist(videoId=video_id)
        lyrics_info = watch.get("lyrics") if isinstance(watch, dict) else None
        if not lyrics_info:
            return None

        browse_id = lyrics_info.get("browseId")
        if not browse_id:
            return None

        dados = yt.get_lyrics(browse_id)
        if dados and dados.get("lyrics"):
            return dados["lyrics"]

        return None

    except Exception as e:
        st.warning(f"Não consegui buscar a letra pelo YouTube Music: {e}")
        return None


def obter_letra_web(titulo: str, artista: str):
    """
    Tenta obter a letra via web usando Genius (lyricsgenius).
    Isso é o equivalente a 'procurar no navegador', mas via API.
    """
    if genius is None:
        return None

    try:
        artista_principal = artista.split(",")[0].strip() if artista else None

        # 1) tenta com título + artista
        if artista_principal:
            song = genius.search_song(titulo, artista_principal)
        else:
            song = genius.search_song(titulo)

        # 2) fallback: busca com "titulo artista"
        if song is None:
            query = f"{titulo} {artista_principal or ''}".strip()
            song = genius.search_song(query)

        if song and song.lyrics:
            return song.lyrics

    except Exception as e:
        st.warning(f"Não consegui buscar a letra na web (Genius): {e}")

    return None


def obter_letra(titulo: str, artista: str, video_id: str):
    """
    Tenta primeiro no YT Music, depois na web (Genius).
    Retorna (letra, origem) ou (None, None).
    """
    letra = obter_letra_ytmusic(video_id)
    if letra:
        return letra, "ytmusic"

    letra_web = obter_letra_web(titulo, artista)
    if letra_web:
        return letra_web, "genius"

    return None, None


def analisar_com_ia(titulo, artista, is_explicit, letra=None):
    # limita o tamanho da letra só por segurança
    letra_limpa = (
        letra
        or "NÃO FOI POSSÍVEL OBTER A LETRA. Use apenas título, artista e tag explícita."
    ).strip()
    if len(letra_limpa) > 6000:
        letra_limpa = letra_limpa[:6000] + "\n\n[trecho final omitido por tamanho]"

    prompt = f"""
    Você é um avaliador de músicas para tocarem em uma ESCOLA, com crianças e adolescentes
    (fundamental II / médio). Seu trabalho é decidir se a música é adequada em português, se for inglês tudo bem.

    Dados da música:
    - Título: {titulo}
    - Artista(s): {artista}
    - Tag explícita do YouTube Music: {"Sim" if is_explicit else "Não"}

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


def buscar_musica(termo):
    """Tenta várias estratégias até achar um resultado com videoId."""
    try:
        # 1) tenta como 'songs'
        resultados = yt.search(termo, filter="songs", limit=3)
        for m in resultados:
            if m.get("videoId"):
                return m

        # 2) tenta como 'videos'
        resultados_v = yt.search(termo, filter="videos", limit=3)
        for m in resultados_v:
            if m.get("videoId"):
                return m

        # 3) busca geral sem filtro (pega qualquer coisa com videoId)
        resultados_all = yt.search(termo, limit=5)
        for m in resultados_all:
            if m.get("videoId"):
                return m

        # nada encontrado com videoId
        return None

    except Exception as e:
        st.error(f"Erro na busca: {e}")
        return None


# --- INTERFACE (FRONT-END) ---

st.title("🎧 DJ IA: Pedidos (modo Escola)")
st.write("A IA analisará a LETRA da música (YT Music e web) para ver se é adequada para tocar em ambiente escolar.")

if erro_setup:
    st.error(f"Erro de configuração principal: {erro_setup}")
if erro_genius:
    st.info(erro_genius)

pedido = st.text_input("Nome da música ou artista", placeholder="Ex: Queen - Bohemian Rhapsody")
botao_enviar = st.button("Enviar Pedido", type="primary")

if botao_enviar and pedido:
    if erro_setup:
        st.error("Não é possível processar pedidos enquanto houver erro de configuração nas APIs.")
    else:
        with st.spinner('🔍 Buscando no YouTube Music...'):
            musica = buscar_musica(pedido)

        if musica:
            # Extraindo dados
            titulo = musica["title"]
            artistas = ", ".join([a["name"] for a in musica["artists"]])
            capa = musica["thumbnails"][-1]["url"]  # melhor thumbnail disponível
            video_id = musica.get("videoId")
            is_explicit = musica.get("isExplicit", False)

            col1, col2 = st.columns([1, 3])
            with col1:
                st.image(capa, width=100)
            with col2:
                st.subheader(titulo)
                st.write(f"👤 {artistas}")
                if is_explicit:
                    st.caption("⚠️ Tag 'Explícita' detectada")

            if not video_id:
                st.error("Não foi possível obter um ID de vídeo válido para essa música.")
            else:
                # Buscar letra (YT Music -> Web/Genius)
                with st.spinner("📝 Buscando a letra da música (YT Music e web)..."):
                    letra, origem = obter_letra(titulo, artistas, video_id)
                    if letra:
                        origem_txt = "YouTube Music" if origem == "ytmusic" else "Genius (web)"
                        st.success(f"Letra encontrada via {origem_txt}.")
                        with st.expander("Ver letra da música"):
                            st.text(letra)
                    else:
                        st.info("Não encontrei a letra dessa música em nenhuma fonte. "
                                "Vou decidir só com título + artista + tag explícita.")

                # Análise da IA
                with st.spinner('🤖 A IA está analisando a letra para ambiente escolar...'):
                    decisao = analisar_com_ia(titulo, artistas, is_explicit, letra)

                if decisao.get("aprovado"):
                    try:
                        resp = yt.add_playlist_items(PLAYLIST_ID, [video_id])
                        status = resp.get("status") if isinstance(resp, dict) else None

                        if status == "STATUS_SUCCEEDED":
                            st.success("✅ APROVADO! Adicionado à playlist da festa da escola.")
                            st.balloons()
                        elif status == "STATUS_DUPLICATE":
                            st.info("ℹ️ A música já estava na playlist, então não foi adicionada de novo.")
                        else:
                            st.warning(f"Resposta da API inesperada: {resp}")
                    except Exception as e:
                        st.error(f"Erro ao adicionar na playlist: {e}")
                    st.caption(f"Motivo da aprovação: {decisao.get('motivo', 'Sem motivo informado')}")
                else:
                    st.error("🚫 RECUSADO PARA AMBIENTE ESCOLAR")
                    st.warning(f"Motivo: {decisao.get('motivo', 'Sem motivo informado')}")
        else:
            st.warning("Música não encontrada no YouTube Music. Tente ser mais específico.")

st.divider()
st.caption("Desenvolvido com Python, Streamlit, YTMusicAPI, Genius (web) e Gemini (modo Escola 🏫)")
