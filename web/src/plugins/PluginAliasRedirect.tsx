import { Navigate, useLocation } from "react-router-dom";

/** Redirect a compatibility route without dropping a shareable query/hash. */
export function PluginAliasRedirect({ to }: { to: string }) {
  const { search, hash } = useLocation();
  return <Navigate to={{ pathname: to, search, hash }} replace />;
}
