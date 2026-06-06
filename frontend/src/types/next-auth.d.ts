/**
 * TypeScript module augmentation for Auth.js v5.
 *
 * The default Session.user type has name/email/image but no `id`, and the JWT
 * has no `id` either. Our jwt/session callbacks in lib/auth.ts put user_id on
 * both, so we widen the types here to match — otherwise session.user.id (the
 * value every V8b call-site reads instead of "idan_demo") is a compile error.
 *
 * This file has no runtime output; it only teaches the compiler. It must sit
 * somewhere TypeScript includes (anywhere under src/ with the default tsconfig)
 * and use `declare module` to merge into next-auth's own types.
 *
 * Versioning:
 *   V8a: this file.
 */

import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    user: {
      id: string;
    } & DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    id?: string;
  }
}
