import { percent } from './format.js'

export function Heading({ name, description, children }) {
  return <div className="ph"><div className="page-heading"><h1>{name}</h1><p>{description}</p></div>
    {children && <div className="r">{children}</div>}</div>
}

export function Tag({ children }) {
  return <span className={`tag ${children}`}>{children}</span>
}

export function Table({ headers, children, empty = 'No records yet.' }) {
  return <div className="workbench-table"><table><thead><tr>{headers.map((text) => <th key={text} scope="col">{text}</th>)}</tr></thead>
    <tbody>{children?.length ? children : <tr><td colSpan={headers.length} className="workbench-empty">{empty}</td></tr>}</tbody></table></div>
}

export function Filters({ options, value, change }) {
  return <span className="seg">{options.map((item) => <button key={item} className={item === value ? 'on' : ''} aria-pressed={item === value} onClick={() => change(item)}>{item}</button>)}</span>
}

export function Confidence({ value }) {
  const amount = percent(value)
  return <span className={`cf ${amount < 80 ? 'lo' : ''}`}><i><b style={{ width: `${amount}%` }} /></i>{amount}</span>
}
