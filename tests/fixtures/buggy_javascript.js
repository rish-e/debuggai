// Test fixture: AI-generated JavaScript with known bugs

// Bug 1: Hallucinated import (this package doesn't exist)
import { magicRouter } from "express-magic-ai";
const autoCache = require("redis-auto-cache-pro");

// Bug 2: XSS vulnerability
function renderUserBio(bio) {
  document.getElementById("bio").innerHTML = bio;
}

// Bug 3: Hardcoded secret
const api_key = "sk-live-abc123def456ghi789jkl012mno345pqr678stu901";

// Bug 4: SQL injection
function getUser(db, username) {
  const query = `SELECT * FROM users WHERE name = '${username}'`;
  return db.query(query);
}

// Bug 5: eval
function parseData(str) {
  return eval(str);
}

// Bug 6: Sensitive data in localStorage
function saveAuth(token) {
  localStorage.setItem("auth_token", token);
}

// Bug 7: CORS wildcard
const corsOptions = {
  origin: "*",
  credentials: true,
};

// Bug 8: fetch in loop
async function fetchAllUsers(ids) {
  const users = [];
  for (const id of ids) {
    const res = await fetch(`/api/users/${id}`);
    users.push(await res.json());
  }
  return users;
}

// Bug 9: Sync file I/O
const fs = require("fs");
function readConfig() {
  return fs.readFileSync("config.json", "utf-8");
}

// Bug 10: dangerouslySetInnerHTML
function HtmlContent({ html }) {
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}
