export default {
  baseURL: process.env.BASE_URL || 'http://localhost:8000',
  timeout: 60000,
  retries: 1,
  use: {
    viewport: { width: 1280, height: 900 },
    headless: true,
    ignoreHTTPSErrors: true,
  },
};
