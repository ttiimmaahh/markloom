# frontend

Single-page app: **React + Vite + Tailwind v4 + shadcn-style components**.

```bash
npm install
npm run dev        # http://localhost:5173 (proxies /api → http://localhost:8000)
npm run build      # emits dist/, which the Dockerfile serves via FastAPI
npm run typecheck
```

- `src/components/Dropzone.tsx` — drag-and-drop upload (react-dropzone)
- `src/components/JobHistory.tsx` — conversion history table with download links
- `src/hooks/useJobs.ts` — loads history and polls while any job is active
- `src/lib/api.ts` — typed client for the FastAPI backend
- `src/components/ui/` — shadcn-style primitives (button, card, table)

`components.json` is configured so `npx shadcn@latest add <component>` works.
