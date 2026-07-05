# Runs the MCP server against a baked-in empty project so directory sandboxes
# (e.g. Glama) can start it and introspect the tools. To serve a real project,
# mount it over /app: docker run -i --rm -v "$PWD":/app <image>
FROM python:3.13-slim
WORKDIR /app
COPY . /src
RUN pip install --no-cache-dir /src && heddle init
ENTRYPOINT ["heddle-mcp"]
