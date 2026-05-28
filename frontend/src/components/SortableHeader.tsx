import type { SortDirection } from "../types";

interface Props<C extends string> {
  column: C;
  label: string;
  activeColumn: C;
  activeDirection: SortDirection;
  onChange: (column: C) => void;
}

export default function SortableHeader<C extends string>({
  column,
  label,
  activeColumn,
  activeDirection,
  onChange,
}: Props<C>) {
  const isActive = activeColumn === column;
  const indicator = isActive ? (activeDirection === "asc" ? "▲" : "▼") : "";
  return (
    <th>
      <button
        type="button"
        className={isActive ? "sort-header active" : "sort-header"}
        onClick={() => onChange(column)}
        aria-sort={isActive ? (activeDirection === "asc" ? "ascending" : "descending") : "none"}
      >
        {label}
        <span className="sort-indicator">{indicator}</span>
      </button>
    </th>
  );
}
