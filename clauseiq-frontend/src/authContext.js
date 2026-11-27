import { createContext, useContext } from 'react'

export const AuthContext = createContext(null)

/** The signed-in user: { username, displayName, role, can: { review, admin }, signOut }. */
export function useAuth() {
  return useContext(AuthContext)
}
