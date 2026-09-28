/**
 * Routes whose content is scoped to one workplace, and which therefore get
 * the workplace switcher in the header. Kept next to the route table (and
 * out of the router module itself, which would be a cycle: router -> layout
 * -> Header) so a new scheduler screen is registered in one place.
 *
 * The mail request is not listed: it offers every workplace of the user at
 * once, so a switcher there would change nothing on the page.
 */
export const WORKPLACE_SCOPED_PATHS = [
  '/ambulances/schedule',
  '/ambulances/print',
  '/departments',
  '/employees',
  '/competences',
  '/special-days',
];

export const isWorkplaceScopedPath = (pathname) =>
  WORKPLACE_SCOPED_PATHS.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`)
  );
