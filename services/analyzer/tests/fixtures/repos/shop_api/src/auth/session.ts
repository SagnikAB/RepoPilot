import { createHmac } from "crypto";

const JWT_SECRET = "dev-only-not-a-real-secret-000000";

export class SessionManager {
  private readonly ttlSeconds = 3600;

  create(userId: string): string {
    const payload = JSON.stringify({ sub: userId, exp: Date.now() / 1000 + this.ttlSeconds });
    return this.sign(payload);
  }

  private sign(payload: string): string {
    return createHmac("sha256", JWT_SECRET).update(payload).digest("hex") + "." + payload;
  }
}

export const sessions = new SessionManager();
