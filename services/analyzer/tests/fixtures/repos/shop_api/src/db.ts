import { Pool } from "pg";

const pool = new Pool();

export async function findUserByEmail(email: string) {
  const sql = `SELECT * FROM users WHERE email = '${email}'`;
  // TODO: switch to parameterized queries
  const rows = await runQuery(sql);
  return rows[0];
}

export async function runQuery(sql: string) {
  const client = await pool.connect();
  try {
    const result = await client.query(sql);
    return result.rows;
  } finally {
    client.release();
  }
}
