/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './core/**/*.html',
    './core/**/*.py',
    './owner/**/*.html',
    './owner/**/*.py',
    './ordering/**/*.html',
    './ordering/**/*.py',
    './kitchen/**/*.html',
    './kitchen/**/*.py',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  '#fff7ed',
          100: '#ffedd5',
          200: '#fed7aa',
          300: '#fdba74',
          400: '#fb923c',
          500: '#f97316',
          600: '#ea580c',
          700: '#c2410c',
          800: '#9a3412',
          900: '#7c2d12',
        },
        accent: '#e85d20',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
