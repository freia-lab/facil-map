FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py map_setup.py photos.py csv_io.py integrations.py backup_support.py floors.json /app/
COPY scripts /app/scripts
COPY static /app/static
RUN useradd --uid 10001 --create-home freia && mkdir /data && chown freia:freia /data
USER freia
VOLUME ["/data"]
EXPOSE 8000
CMD ["python", "server.py", "--host", "0.0.0.0", "--auth", "accounts", "--data", "/data/freia.sqlite3"]
