# 🩺 Guia Médica Unimed Porto Alegre — Preenchimento Digital (Streamlit)

Aplicação web em **Streamlit** para preenchimento, visualização e impressão da **Nota de Procedimento em Hospital (Procedimentos sem Autorização Prévia)** da Unimed Porto Alegre, utilizando a guia original (`Quadrados.pdf`) como plano de fundo e a tabela **CBHPM 2014** integrada (4.498 procedimentos).

## 📦 Arquivos Necessários para Publicação no Streamlit Cloud (`share.streamlit.io`)

Ao subir para o seu repositório no GitHub, inclua os seguintes arquivos desta pasta:
1. `app.py` — Aplicação principal Streamlit.
2. `requirements.txt` — Dependências Python (`streamlit`, `pandas`, `reportlab`, `pypdf`).
3. `cbhpm.csv` — Catálogo com os 4.498 procedimentos da CBHPM.
4. `Quadrados.pdf` (e/ou `guia dos quadradinhos.pdf`) — Template oficial da guia médica usado como plano de fundo.

## 🚀 Passo a Passo para Publicar no Streamlit Community Cloud

1. Crie um repositório no [GitHub](https://github.com/new) (pode ser **Público** ou **Privado**).
2. Faça upload dos arquivos `app.py`, `requirements.txt`, `cbhpm.csv` e `Quadrados.pdf` na raiz do repositório.
3. Acesse [share.streamlit.io](https://share.streamlit.io/) e faça login com sua conta do GitHub.
4. Clique em **Create app** -> **Yup, I have an app**.
5. Selecione o seu repositório, a branch (`main`) e defina **Main file path** como `app.py`.
6. Clique em **Deploy!**. Em cerca de 1 a 2 minutos seu app estará online.
