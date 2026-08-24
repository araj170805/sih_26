// =====================================================
// AUTH — Firebase email/password sign-in & registration
// with seamless local backend JWT authentication fallback.
// =====================================================

import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  updateProfile,
} from "firebase/auth";
import { api, clearSession, saveSession } from "./api.js";
import { firebaseReady, requireFirebase } from "./firebase.js";

// -----------------------------------------------------
// STARFIELD BACKGROUND
// -----------------------------------------------------

const canvas = document.getElementById("authStars");

if (canvas) {
  const ctx = canvas.getContext("2d");
  let stars = [];

  function resize() {
    canvas.width = innerWidth;
    canvas.height = innerHeight;
    stars = Array.from({ length: 120 }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 1.2 + 0.3,
    }));
  }

  addEventListener("resize", resize);
  resize();

  (function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#e8a87c";
    for (const s of stars) {
      ctx.globalAlpha = 0.25 + Math.random() * 0.4;
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(draw);
  })();
}

// -----------------------------------------------------
// FRIENDLY FIREBASE ERROR MESSAGES
// -----------------------------------------------------

const FIREBASE_ERRORS = {
  "auth/email-already-in-use": "That email already has an account.",
  "auth/invalid-email": "Please enter a valid email address.",
  "auth/weak-password": "Password is too weak (minimum 6 characters).",
  "auth/user-not-found": "No account found with that email.",
  "auth/wrong-password": "Incorrect password.",
  "auth/invalid-credential": "Invalid email or password.",
  "auth/too-many-requests": "Too many attempts — try again shortly.",
  "auth/network-request-failed": "Network error — check your connection.",
};

function friendlyError(error) {
  return (
    FIREBASE_ERRORS[error?.code] ||
    error?.message?.replace("Firebase: ", "") ||
    "Authentication failed."
  );
}

// -----------------------------------------------------
// FORM HANDLING
// -----------------------------------------------------

const form = document.querySelector("form");
const errorBox = document.getElementById("authError");
const submitBtn = document.getElementById("submitBtn");

const isRegister = Boolean(document.getElementById("registerForm"));

// Prefill email when redirected from "Sign in instead →".
const prefillEmail = new URLSearchParams(location.search).get("email");

if (prefillEmail) {
  const emailInput = document.getElementById("email");

  if (emailInput && !isRegister) {
    emailInput.value = prefillEmail;
    document.getElementById("password")?.focus();
  }
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function showEmailExists(email) {
  errorBox.innerHTML =
    `That email already has an account. ` +
    `<a href="/login.html?email=${encodeURIComponent(email)}" ` +
    `style="color:var(--accent)">Sign in instead →</a>`;
  errorBox.hidden = false;
}

function busy(state, label) {
  submitBtn.disabled = state;
  submitBtn.textContent = state ? label : isRegister ? "REGISTER" : "SIGN IN";
}

async function syncBackendProfile(idToken, extra = {}) {
  // Registers/maps the Firebase user on our backend and stores role.
  const user = await api("/auth/firebase-session", {
    method: "POST",
    body: JSON.stringify({ id_token: idToken }),
  });

  clearSession();
  saveSession({ user: { ...user, ...extra } });

  location.href = "/app.html";
}

async function handleLocalAuth(email, password, username) {
  const endpoint = isRegister ? "/auth/register" : "/auth/login";
  const payload = isRegister
    ? { email, username: username || email.split("@")[0], password }
    : { email, password };

  const data = await api(endpoint, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  clearSession();
  saveSession(data);
  location.href = "/app.html";
}

form?.addEventListener("submit", async (event) => {
  event.preventDefault();

  errorBox.hidden = true;

  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  const username = document.getElementById("username")?.value.trim() || email.split("@")[0];

  busy(true, isRegister ? "CREATING ACCOUNT…" : "SIGNING IN…");

  if (firebaseReady) {
    try {
      const auth = requireFirebase();

      if (isRegister) {
        let credential;
        try {
          credential = await createUserWithEmailAndPassword(auth, email, password);
        } catch (regError) {
          if (regError?.code === "auth/email-already-in-use") {
            busy(false);
            showEmailExists(email);
            return;
          }
          throw regError;
        }

        if (username) {
          await updateProfile(credential.user, { displayName: username });
        }

        await syncBackendProfile(await credential.user.getIdToken(), { username });
      } else {
        const credential = await signInWithEmailAndPassword(auth, email, password);
        await syncBackendProfile(await credential.user.getIdToken(), {
          username: credential.user.displayName || email.split("@")[0],
        });
      }
      return;
    } catch (firebaseErr) {
      console.warn("[AUTH] Firebase auth failed, attempting backend local auth...", firebaseErr);
    }
  }

  // Local backend auth fallback
  try {
    await handleLocalAuth(email, password, username);
  } catch (localErr) {
    if (localErr.status === 409 || localErr.message?.includes("already registered")) {
      showEmailExists(email);
    } else {
      showError(localErr.message || "Authentication failed.");
    }
    busy(false);
  }
});
