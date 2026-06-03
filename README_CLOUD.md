# ☁️ Aquera Premium Hub - Cloud Deployment Guide

This guide provides step-by-step instructions to deploy the full **Aquera Documentation Hub & Insights Dashboard** to a dedicated cloud platform. 

Unlike serverless platforms (like Vercel), container platforms support long-running processes, fully writable local file systems, and background web browsers (Playwright Chromium) needed to sync Zendesk and generate high-fidelity PDF manuals.

---

## 🚀 Option A: Deploying to Render.com (Easiest & Recommended)

Render offers a powerful, fully-managed container platform that supports deploying directly from GitHub with our pre-configured `Dockerfile` and `render.yaml`.

### Step 1: Push your Code to GitHub
1. Create a private repository on GitHub (e.g., `aquera-premium-doc`).
2. Push your codebase to the repository:
   ```bash
   git init
   git add .
   git commit -m "feat: Add Docker and Render configurations"
   git remote add origin <your-github-repo-url>
   git branch -M main
   git push -u origin main
   ```

### Step 2: One-Click Deploy on Render
1. Log into your account at [Render.com](https://render.com).
2. Click **New +** in the top right and select **Blueprints**.
3. Connect your GitHub account and select your `aquera-premium-doc` repository.
4. Render will read the `render.yaml` file automatically and present the deployment configurations.
5. Provide your Zendesk Credentials as Environment Variables when prompted:
   * `ZENDESK_SUBDOMAIN` (e.g., `aquera`)
   * `ZENDESK_EMAIL` (e.g., `user@aquera.com`)
   * `ZENDESK_TOKEN` (your API token)
6. Click **Approve**! Render will build your Docker container, install Chromium, and launch your live URL in 3-4 minutes.

---

## 🦄 Option B: Deploying to Heroku

Heroku's Container Registry allows running full-scale Docker applications with instant SSL.

### Step 1: Install Heroku CLI & Login
1. Download and install the [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli).
2. Log in and initialize container plugins in your terminal:
   ```bash
   heroku login
   heroku container:login
   ```

### Step 2: Create and Deploy the App
1. Create a new Heroku app:
   ```bash
   heroku create aquera-premium-hub
   ```
2. Configure your Zendesk Credentials:
   ```bash
   heroku config:set ZENDESK_SUBDOMAIN="aquera" ZENDESK_EMAIL="user@aquera.com" ZENDESK_TOKEN="your_token_here"
   ```
3. Build and push the Docker image to Heroku:
   ```bash
   heroku container:push web
   ```
4. Release the container live:
   ```bash
   heroku container:release web
   ```
5. Open your live app:
   ```bash
   heroku open
   ```

---

## 🌊 Option C: Deploying to DigitalOcean App Platform

DigitalOcean App Platform provides robust container hosting with easy Git integration.

### Step 1: Initialize App Creation
1. Go to your [DigitalOcean Control Panel](https://cloud.digitalocean.com).
2. Click **Apps** in the sidebar, and then click **Create App**.
3. Choose **GitHub** as the source, select your repository, and click **Next**.

### Step 2: Configure Build Settings
1. DigitalOcean will automatically detect the `Dockerfile` in the root of your project.
2. In **Environment Variables**, add:
   * `PORT`: `5001`
   * `ZENDESK_SUBDOMAIN`
   * `ZENDESK_EMAIL`
   * `ZENDESK_TOKEN`
3. Click **Next**, choose a pricing plan (starts at $5/month for basic containers), and click **Create Resources** to launch your live platform!
