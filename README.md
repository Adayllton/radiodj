# DJ IA - Streamlit

Pequeno projeto de site web para pedidos de música com moderação via IA.

## Arquivos

- `app.py` — Aplicação Streamlit principal.
- `requirements.txt` — Dependências Python.
- `oauth.json` — Arquivo de autenticação da sua conta do YouTube Music (não vem pronto no zip).
  - Use o `YTMusic.setup(...)` conforme explicamos antes para gerar esse arquivo.

## Como usar

1. Crie e ative um ambiente virtual (opcional, mas recomendado).
2. Instale as dependências:

   ```bash
   pip install -r requirements.txt
   ```

3. Coloque o arquivo `oauth.json` na mesma pasta do `app.py`.
4. Edite o topo do `app.py` e preencha:
   - `GEMINI_API_KEY`
   - `PLAYLIST_ID`
5. Rode o site:

   ```bash
   streamlit run app.py
   ```

6. Use a URL local ou de rede que o Streamlit mostrar para compartilhar na festa.
