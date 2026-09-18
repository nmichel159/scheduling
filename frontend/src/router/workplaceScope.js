/**
 * Routes whose content is scoped to one workplace, and which therefore get
 * the workplace switcher in the header. Kept next to the route table (and
 * out of the router module itself, which would be a cycle: router -> layout
 * -> Header) so a new scheduler screen is registered in one place.
 */
export const WORKPLACE_SCOPED_PATHS = [
  '/ambulances/schedule',
  '/ambulances/workload',
  '/departments',
];

export const isWorkplaceScopedPath = (pathname) =>
  WORKPLACE_SCOPED_PATHS.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`)
  );
