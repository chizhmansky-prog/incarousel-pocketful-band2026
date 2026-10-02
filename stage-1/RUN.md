# Run

Build: `docker build -t pocketful-stage .`

Run: `docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage`

Health: `curl http://localhost:8080/health`
