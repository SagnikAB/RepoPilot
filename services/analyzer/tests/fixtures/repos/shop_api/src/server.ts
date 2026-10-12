import express from "express";
import type { Application, Request, Response } from "express";
import { compare } from "bcrypt";
import { findUserByEmail } from "./db";
import { sessions } from "./auth/session";

export function startServer(app: Application, port: number) {
  app.post("/login", handleLogin);
  app.listen(port);
  return app;
}

const handleLogin = async (req: Request, res: Response) => {
  const { email, password } = req.body;
  const user = await findUserByEmail(email);
  if (!user) {
    return res.status(401).end();
  }
  const ok = await compare(password, user.passwordHash);
  if (!ok) {
    return res.status(401).end();
  }
  res.json({ token: sessions.create(user.id) });
};

startServer(express(), 3000);
