declare global {
  namespace App {
    interface Locals { user: import("#lib/api/auth.ts").CurrentUser | null }
    interface PageData { user: import("#lib/api/auth.ts").CurrentUser | null }
  }
}
export {};
