import ytmusicapi


RAW_HEADERS = """\
:authority: music.youtube.com
:method: POST
:path: /api/stats/atr?ns=yt&el=detailpage&cpn=eBTa7m6xoPP0XjwC&ver=2&cmt=0.495&fmt=0&fs=0&rt=4.479&euri&lact=208&cl=834519076&mos=0&volume=100&cbr=Chrome&cbrver=142.0.0.0&c=WEB_REMIX&cver=1.20251119.03.01&cplayer=UNIPLAYER&cos=Windows&cosver=10.0&cplatform=DESKTOP&hl=pt_BR&cr=BR&uga=m22&len=212&fexp=v1%2C24004644%2C27005591%2C53408%2C34656%2C47714%2C58316%2C18644%2C104298%2C13391%2C9252%2C3479%2C13030%2C6258%2C16948%2C15179%2C2%2C20221%2C19814%2C39377%2C5345%2C764%2C9720%2C5385%2C25059%2C4174%2C15046%2C10672%2C4729%2C1257%2C7922%2C9272%2C254%2C1734%2C563%2C9567%2C1488%2C5548%2C2537%2C137%2C6062%2C293%2C3317%2C1370%2C2010%2C1052%2C1368%2C1484%2C167%2C327%2C4926%2C4478%2C671%2C49%2C1206%2C1934%2C920%2C1242%2C661%2C1835%2C41%2C582%2C4165%2C395%2C2386%2C5381%2C8364%2C75%2C6126%2C99%2C5151%2C834%2C2628%2C1661%2C916%2C737%2C1354%2C1839%2C998%2C739%2C6352%2C5441&afmt=251&muted=0&vis=10&docid=MVeoG6Au4zE&ei=CeAkafH3F_KQ-LAPgs2UgQM&plid=AAZEXuuJGGr_6_OK&vm=CAMQARgBOjJBSHFpSlRKTlFTdFFPZ0V1RWY4Z2RSMW50YmtxeEVoTDBHQkZkQWZzT2dVeU5qV2pWd2JYQUZVQTZSUUx1OGJjMmRCZGNCT09aeVdBdVJ2N1pDSGwtMC03c3pucWFLU3dBV29VbWlSUHhoVkhWMU1WSlRxekU1bGkzWFEzSDZtZ2dkX19LRy1UVEVzYbgBAQ
:scheme: https
accept: */*
accept-encoding: gzip, deflate, br, zstd
accept-language: pt-BR,pt;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6
content-length: 3931
content-type: application/x-www-form-urlencoded
cookie: SOCS=CAISNQgREitib3FfaWRlbnRpdHlmcm9udGVuZHVpY2VydmVyXzIwMjUwNzExLjA2X3AwGgJwdCACGgYIgJHRwwY; VISITOR_INFO1_LIVE=DSQy-UUto-M; VISITOR_INFO1_LIVE=DSQy-UUto-M; VISITOR_PRIVACY_METADATA=CgJCUhIEGgAgUQ%3D%3D; VISITOR_PRIVACY_METADATA=CgJCUhIEGgAgUQ%3D%3D; LOGIN_INFO=AFmmF2swRAIgSnqBwLhRAXkEyX1Tt9a7vNoR-vX2m83viyY9JHO-Hs8CIC0bCGn2zCnxL_iBLCKdp8audbabFjl1aKv-9s_2BxHV:QUQ3MjNmemRnTlZkdjZocUhUQkkyZWw0VjFaYXZYYW15NklndE5ESDRGSkpXdGYtaHEwMWpBZU9uZy1NMzZMbGxka0NzZzdDbV93Q21zaGpCQkpOZW8zQTc3ZlJkWXZINlBHUnk5aXFFT3NPeU9QT2cxYWFWYmN3NDNRRUY1cmxQNy1vVnJNV3ZGVmJoanczWkk4WkJCc3kzT0RMLXk2NTdR; PREF=f6=400&volume=100&f7=100&tz=America.Sao_Paulo&repeat=NONE&guide_collapsed=false&f4=4000000&autoplay=true; HSID=A4mb_gqfxOJwXka_o; SSID=AvxMyKd17M_MAYQFl; APISID=RJIRGJpdq33EXJ6i/A0etJVK4gFmDTcXU7; SAPISID=7M49jgtIF5mlbVNG/As3dfP5NyebjtMdXm; __Secure-1PAPISID=7M49jgtIF5mlbVNG/As3dfP5NyebjtMdXm; __Secure-3PAPISID=7M49jgtIF5mlbVNG/As3dfP5NyebjtMdXm; YSC=EenXdojjf9Y; __Secure-ROLLOUT_TOKEN=CN3xoon8robcSBDtgOXE86CLAxjjz_y4qIuRAw%3D%3D; SID=g.a0003wiEXIjaUyKWRYMLz0cnXCZILlW6Tj8yOWEBn9aSXVcEJLECAUWVdn4qO4pa8W8zoPUwKgACgYKAWISARcSFQHGX2MiwRPVZVDy61AsfyG3KEhwfxoVAUF8yKpCTP8-ipRbPgyTbY7Ha6VW0076; __Secure-1PSID=g.a0003wiEXIjaUyKWRYMLz0cnXCZILlW6Tj8yOWEBn9aSXVcEJLEC9anvtYJSoyvp9eOQc0J9rgACgYKARESARcSFQHGX2Mi2tbSAnNqMDnG-_YCtYON-hoVAUF8yKpOoEc9xaMDVZV67L2qsbjp0076; __Secure-3PSID=g.a0003wiEXIjaUyKWRYMLz0cnXCZILlW6Tj8yOWEBn9aSXVcEJLECRtrPIxVDy5ktKh9dSu1d0QACgYKAf4SARcSFQHGX2MickqFKofkakVD5C9oU2y-1RoVAUF8yKoIebCenVF8OKgOPvfc84Je0076; funnelData={"loupe":{"percent":99,"isPanelShown":false},"cursor":{"percent":78,"isPanelShown":false},"blurb":{"percent":92,"isPanelShown":false},"darkmood":{"percent":24,"isPanelShown":false}}; __Secure-1PSIDTS=sidts-CjUBwQ9iI16Yq5dP6Fy7sGx7SASv1W8IS0sgJG3O5Rh7u2dyukROv5v1Sfk1Z0b2jFPlMpNIuxAA; __Secure-3PSIDTS=sidts-CjUBwQ9iI16Yq5dP6Fy7sGx7SASv1W8IS0sgJG3O5Rh7u2dyukROv5v1Sfk1Z0b2jFPlMpNIuxAA; SIDCC=AKEyXzUx8Kw5Xi0NRit30dasb3_wCReT3yz9xV7A-0cbuQoS49_rk0cymqfbeoO29xhjP0dc7WM; __Secure-1PSIDCC=AKEyXzV3qzYNBGUbo-ZjGItAl9lG-V3_Q58iwCUwf6Yul7CnYaixydYD_nhb08B1c0qqrVvV-sE; __Secure-3PSIDCC=AKEyXzVX3oZbVlyt-UR0XS1QXjYwWEC41jAvWGfKFsU5bvcRaZHCJJixQOUa_l_nUHhePvGTeD8; CONSISTENCY=AKreu9va6p2IyPr0eHNon-8JlOC7Tj_-xqNdkEMAvyiMoD41TRLN7ahEfsEXhFFPQOpZP0KQwiLa7AUH5Zy5PqMnXXOQFcEug7pnA-WkhxCNX2HKpdL81l_nly9usHXkkUZeK80g_OtYEAVijhbsKLaXi1vgX6-kFcyNjL9U3CcOqyCjkq93V6Qx2Pj0DhXymRlA1IdPKUflkOe5DAmiHpwgcExvRpLTjcJqzpNz5x9ndZ4VvaapMev3z4N6I1ZNOAgIS8VdqKR1oXDRi5URcpjiuXcAyHZHtd95dab1mgSqpg
dnt: 1
origin: https://music.youtube.com
priority: u=1, i
referer: https://music.youtube.com/watch?v=MVeoG6Au4zE&list=PL_45f9jLesgjdE5usz75-zDtBt7ChSM5f
sec-ch-ua: "Chromium";v="142", "Not_A Brand";v="99", "Google Chrome";v="142"
sec-ch-ua-arch: "x86"
sec-ch-ua-bitness: "64"
sec-ch-ua-form-factors: "Desktop"
sec-ch-ua-full-version: "142.0.7444.176"
sec-ch-ua-full-version-list: "Chromium";v="142.0.7444.176", "Not_A Brand";v="99.0.0.0", "Google Chrome";v="142.0.7444.176"
sec-ch-ua-mobile: ?0
sec-ch-ua-model: ""
sec-ch-ua-platform: "Windows"
sec-ch-ua-platform-version: "19.0.0"
sec-ch-ua-wow64: ?0
sec-fetch-dest: empty
sec-fetch-mode: cors
sec-fetch-site: same-origin
user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36
x-browser-channel: stable
x-browser-copyright: Copyright 2025 Google LLC. All rights reserved.
x-browser-validation: Aj9fzfu+SaGLBY9Oqr3S7RokOtM=
x-browser-year: 1969
x-goog-authuser: 0
x-goog-event-time: 1764024334056
x-goog-request-time: 1764024334056
x-goog-visitor-id: CgtEU1F5LVVVdG8tTSjLkZPJBjIKCgJCUhIEGgAgUQ%3D%3D
x-youtube-ad-signals: dt=1764018380433&flash=0&frm&u_tz=-180&u_his=11&u_h=864&u_w=1536&u_ah=864&u_aw=1536&u_cd=24&bc=31&bih=710&biw=328&brdim=0%2C0%2C0%2C0%2C1536%2C0%2C1536%2C864%2C328%2C710&vis=1&wgl=true&ca_type=image
x-youtube-client-name: 67
x-youtube-client-version: 1.20251119.03.01
x-youtube-datasync-id: 112545150040526945435||
x-youtube-device: cbr=Chrome&cbrver=142.0.0.0&ceng=WebKit&cengver=537.36&cos=Windows&cosver=10.0&cplatform=DESKTOP
x-youtube-identity-token: QUFFLUhqbHRZWmFPc0lCdlBzRC0tRURoVDAzUVcxY3VEUXw=
x-youtube-page-cl: 834223799
x-youtube-page-label: youtube.music.web.client_20251119_03_RC01
x-youtube-time-zone: America/Sao_Paulo
x-youtube-utc-offset: -180
"""

def main():
    ytmusicapi.setup(filepath="oauth.json", headers_raw=RAW_HEADERS)
    print("✅ Arquivo oauth.json gerado com sucesso.")


if __name__ == "__main__":
    main()
