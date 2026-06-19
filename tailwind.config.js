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
          50:  '#f0f7ff',
          100: '#e0effe',
          200: '#bae0fd',
          300: '#7cc8fb',
          400: '#36abf7',
          500: '#0c91eb',
          600: '#0071c9',
          700: '#005aa3',
          800: '#1a3c5e',
          900: '#0a233d',
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
