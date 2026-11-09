# Free demo on Streamlit Community Cloud

The full system (backend, gateway, PostgreSQL with pgvector, Redis, a model key) does not fit a free host, and it would put
a model key on the internet. So the public demo is a separate screen, `ui/demo_app.py`, that shows answers **recorded from the
real system**. It needs no backend, no database, no environment variable and no secret.

What it is, honestly: a replay of real answers to a fixed list of questions, rendered with the same code as the live screen.
It is not a live model. The screen says so at the top, and a question that was not recorded gets "not in this demo".

## Deploy (about five minutes, done by the repository owner)

1. Sign in at https://share.streamlit.io with the GitHub account that owns the repository.
2. New app, then pick the repository, the branch `main`, and the main file path `ui/demo_app.py`.
3. Advanced settings: Python 3.12. No secrets are needed.
4. Deploy. Streamlit installs `ui/requirements.txt` and starts the screen.
5. Put the public address in the README (the "Live demo" line) and in the LinkedIn post.

## Run it locally

```
cd ui
pip install -r requirements.txt
streamlit run demo_app.py
```

## Re-record the answers

The answers carry the dates of the day the data was seeded (return and exchange windows). After re-seeding, or after any
change in the answers, record them again from the running stack:

```
docker compose up -d
python ui/demo/record.py
```

Then run `pytest ui/tests/test_demo.py`: it checks that every recording renders to readable text with no leftover
placeholder, and that no token or password is stored in the recordings.
