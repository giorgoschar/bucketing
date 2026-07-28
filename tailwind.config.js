/**
 * Mirrors the config that used to live inline in base.html alongside the
 * cdn.tailwindcss.com script tag.
 *
 * `content` must include the static JS: base.html and the component files build
 * class strings at runtime (the offline queue pill picks bg-amber-500 /
 * bg-red-500 / bg-emerald-500 by state). Those never appear in markup, so
 * without scanning them the classes are purged and the element renders unstyled.
 */
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './static/*.js',
  ],
  theme: {
    extend: {
      colors: {
        /* The five shades that were defined inline are exactly Tailwind's
           indigo. Templates also reference primary-300, -400 and -900, which
           were never defined — those classes silently produced nothing, with
           the CDN too, leaving hover states and dark-mode tints unstyled.
           Completing the scale makes the existing markup work as written. */
        primary: {
          50:  '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
          950: '#1e1b4b',
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
