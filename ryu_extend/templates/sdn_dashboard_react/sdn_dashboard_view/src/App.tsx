import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import Topology from './pages/Topology';
import Flows from './pages/Flows';
import Apps from './pages/Apps';
import './App.css';

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-layout">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/topology" element={<Topology />} />
            <Route path="/flows" element={<Flows />} />
            <Route path="/apps" element={<Apps />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
