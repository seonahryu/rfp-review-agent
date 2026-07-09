export const BACKEND_API_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || "https://rfp-review-agent.onrender.com"
).replace(/\/$/, "")
