import { Link } from "react-router-dom";

export default function Dashboard() {
  return (
    <div>
      <h1>Dashboard</h1>
      <p>Operational intelligence surfaces for space surveillance analysts.</p>
      <div className="card">
        <h2>Data sources</h2>
        <ul>
          <li>
            <Link to="/elsets">Element sets (UDL)</Link>
          </li>
        </ul>
      </div>
    </div>
  );
}
