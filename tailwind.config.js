/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    // Django 템플릿 위치를 지정 (예시)
    "./templates/**/*.html",
    "./cs_management/templates/**/*.html",
    "./delayed_management/templates/**/*.html",
    "./return_process/templates/**/*.html",
    // 필요하다면 *.js, *.jsx, *.ts, *.tsx 파일 등도 추가
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}