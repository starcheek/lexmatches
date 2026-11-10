# Welcome to your Lovable project

## Project info

**URL**: https://lovable.dev/projects/94e0d088-e27c-41e5-aea3-87fd532f2cbb

## Local development

Requires Node 22 and Docker Desktop (running).

```sh
npm install
npm run db:start      # local Supabase in Docker, applies supabase/migrations
cp supabase/functions/.env.example supabase/functions/.env   # fill AI_API_KEY etc.
npm run functions     # edge functions with hot reload (restart after .env changes)
npm run dev           # http://localhost:8080
npm run smoke         # end-to-end pipeline check
```

`.env.development.local` points `npm run dev` at the local stack; delete it to use the hosted project.

| Service | URL |
|---|---|
| App | http://localhost:8080 |
| Supabase API | http://127.0.0.1:54321 |
| Studio (DB UI) | http://127.0.0.1:54323 |
| Mailpit (auth emails) | http://127.0.0.1:54324 |
| Postgres | postgresql://postgres:postgres@127.0.0.1:54322/postgres |

Other: `npm run db:reset` (re-apply migrations, wipes data), `npm run db:types` (regenerate `src/integrations/supabase/types.ts`), `npm run db:stop`.

## How can I edit this code?

There are several ways of editing your application.

**Use Lovable**

Simply visit the [Lovable Project](https://lovable.dev/projects/94e0d088-e27c-41e5-aea3-87fd532f2cbb) and start prompting.

Changes made via Lovable will be committed automatically to this repo.

**Use your preferred IDE**

If you want to work locally using your own IDE, you can clone this repo and push changes. Pushed changes will also be reflected in Lovable.

The only requirement is having Node.js & npm installed - [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating)

Follow these steps:

```sh
# Step 1: Clone the repository using the project's Git URL.
git clone <YOUR_GIT_URL>

# Step 2: Navigate to the project directory.
cd <YOUR_PROJECT_NAME>

# Step 3: Install the necessary dependencies.
npm i

# Step 4: Start the development server with auto-reloading and an instant preview.
npm run dev
```

**Edit a file directly in GitHub**

- Navigate to the desired file(s).
- Click the "Edit" button (pencil icon) at the top right of the file view.
- Make your changes and commit the changes.

**Use GitHub Codespaces**

- Navigate to the main page of your repository.
- Click on the "Code" button (green button) near the top right.
- Select the "Codespaces" tab.
- Click on "New codespace" to launch a new Codespace environment.
- Edit files directly within the Codespace and commit and push your changes once you're done.

## What technologies are used for this project?

This project is built with:

- Vite
- TypeScript
- React
- shadcn-ui
- Tailwind CSS

## How can I deploy this project?

Simply open [Lovable](https://lovable.dev/projects/94e0d088-e27c-41e5-aea3-87fd532f2cbb) and click on Share -> Publish.

## Can I connect a custom domain to my Lovable project?

Yes, you can!

To connect a domain, navigate to Project > Settings > Domains and click Connect Domain.

Read more here: [Setting up a custom domain](https://docs.lovable.dev/features/custom-domain#custom-domain)
