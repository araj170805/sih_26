// =====================================================
// FIREBASE — client initialization
//
// Fill frontend/.env (copy .env.example):
//   VITE_FIREBASE_API_KEY=...
//   VITE_FIREBASE_AUTH_DOMAIN=your-app.firebaseapp.com
//   VITE_FIREBASE_PROJECT_ID=your-app
//   VITE_FIREBASE_APP_ID=1:123456789:web:abcdef
//
// Firebase console -> Project settings -> General -> Your apps.
// Enable Authentication -> Sign-in method -> Email/Password.
// =====================================================

import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export const firebaseReady = Boolean(
  firebaseConfig.apiKey && firebaseConfig.projectId,
);

let auth = null;

if (firebaseReady) {
  const app = initializeApp(firebaseConfig);
  auth = getAuth(app);
} else {
  console.warn(
    "[Orbital Guardian] Firebase not configured — set VITE_FIREBASE_* " +
      "variables in frontend/.env. Falling back to legacy local auth.",
  );
}

export function requireFirebase() {
  if (!auth) {
    throw new Error(
      "Firebase is not configured. Add your VITE_FIREBASE_* values to " +
        "frontend/.env and restart the dev server.",
    );
  }

  return auth;
}

export default auth;
