/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/templates/**/*.html',
    './app/**/*.py'
  ],
  theme: {
    extend: {
      colors: {
        primary: '#ff8419',
      }
    },
  },
  plugins: [],
}

