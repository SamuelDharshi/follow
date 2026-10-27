# Follow web app

Next.js (App Router) front end for Follow. It only reads the Follow API; it holds no data of its own.

```bash
cd web
npm install
NEXT_PUBLIC_API_URL=http://localhost:8010 npm run dev -- -p 3010
```

Pages: `/` landing, `/ask` the investigator agent, `/scorecard`, `/designer`, `/methodology`, `/data`.
`NEXT_PUBLIC_API_URL` must point at a running Follow API (see the root README).
