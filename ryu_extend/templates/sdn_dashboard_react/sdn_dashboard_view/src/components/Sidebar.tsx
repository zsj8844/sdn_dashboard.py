import { NavLink } from 'react-router-dom';

const links = [
  { to: '/', label: '总览', icon: '◉' },
  { to: '/topology', label: '拓扑', icon: '⬡' },
  { to: '/flows', label: '流表', icon: '⇄' },
  { to: '/apps', label: '应用', icon: '⬢' },
];

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <h1>SDN Panel</h1>
        <span className="sidebar-sub">IoT 控制系统</span>
      </div>
      <nav className="sidebar-nav">
        {links.map(({ to, label, icon }) => (
          <NavLink key={to} to={to} end={to === '/'}>
            <span className="nav-icon">{icon}</span>
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
