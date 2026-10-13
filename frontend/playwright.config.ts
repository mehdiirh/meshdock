import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./e2e',use:{baseURL:'http://127.0.0.1:4177',viewport:{width:1440,height:1000}},webServer:{command:'npm run dev -- --port 4177 --strictPort',url:'http://127.0.0.1:4177',reuseExistingServer:false}});
