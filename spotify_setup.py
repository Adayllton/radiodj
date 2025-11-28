# spotify_setup.py
import spotipy
from spotipy.oauth2 import SpotifyOAuth

def setup_spotify_token():
    print("🎵 Configuração do Spotify para DJ IA Escola")
    print("=" * 50)
    
    # Peça as credenciais
    client_id = input("Cole seu SPOTIFY_CLIENT_ID: ").strip()
    client_secret = input("Cole seu SPOTIFY_CLIENT_SECRET: ").strip()
    redirect_uri = "http://localhost:8888/callback"
    
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

if __name__ == "__main__":
    setup_spotify_token()