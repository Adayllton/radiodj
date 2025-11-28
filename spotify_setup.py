# spotify_setup.py - Execute este script localmente
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import webbrowser

def setup_spotify():
    print("🎵 Configuração do Spotify para DJ IA Escola")
    print("=" * 50)
    
    # Peça as credenciais se não estiverem nos secrets
    client_id = input("Cole seu SPOTIFY_CLIENT_ID: ").strip()
    client_secret = input("Cole seu SPOTIFY_CLIENT_SECRET: ").strip()
    redirect_uri = "https://radiodj.streamlit.app/"
    
    # Peça o ID da playlist
    playlist_url = input("Cole o URL completo da sua playlist do Spotify: ").strip()
    
    # Extrai o ID da playlist do URL
    if "playlist/" in playlist_url:
        playlist_id = playlist_url.split("playlist/")[1].split("?")[0]
        print(f"🎧 ID da playlist extraído: {playlist_id}")
    else:
        playlist_id = playlist_url
        print(f"🎧 Usando como ID da playlist: {playlist_id}")
    
    print("\n🔐 Iniciando autenticação...")
    
    try:
        sp_oauth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="playlist-modify-public playlist-modify-private",
            cache_path=".spotify_cache"
        )
        
        # Tenta autenticar
        token_info = sp_oauth.get_access_token()
        
        if token_info:
            sp = spotipy.Spotify(auth=token_info['access_token'])
            user = sp.current_user()
            print(f"✅ Autenticado com sucesso como: {user['display_name']}")
            
            # Testa adicionar uma música (opcional)
            try:
                # Busca uma música de teste
                results = sp.search(q="Queen Bohemian Rhapsody", type="track", limit=1)
                if results['tracks']['items']:
                    test_track = results['tracks']['items'][0]
                    print(f"🎵 Música de teste encontrada: {test_track['name']}")
            except Exception as e:
                print(f"⚠️ Aviso: {e}")
            
            print("\n🎉 CONFIGURAÇÃO CONCLUÍDA!")
            print("\n📋 Adicione estas variáveis aos seus secrets:")
            print(f"SPOTIFY_CLIENT_ID = \"{client_id}\"")
            print(f"SPOTIFY_CLIENT_SECRET = \"{client_secret}\"")
            print(f"SPOTIFY_REDIRECT_URI = \"{redirect_uri}\"")
            print(f"SPOTIFY_PLAYLIST_ID = \"{playlist_id}\"")
            
        else:
            print("❌ Falha na autenticação")
            
    except Exception as e:
        print(f"❌ Erro durante a configuração: {e}")
        print("\n💡 Dicas de solução:")
        print("1. Verifique se o Client ID e Secret estão corretos")
        print("2. Certifique-se de que adicionou o Redirect URI no Spotify Dashboard")
        print("3. Tente novamente")

if __name__ == "__main__":
    setup_spotify()