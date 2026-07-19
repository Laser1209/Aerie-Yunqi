import { useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { navigation } from '../config/navigation'
import { release } from '../config/release'
import { ArrowUpRight } from './icons'

export default function SiteHeader() {
  const [open, setOpen] = useState(false)
  const location = useLocation()

  const close = () => setOpen(false)

  return (
    <header className="fixed inset-x-0 top-4 z-50 flex items-center justify-between px-5 md:px-8 lg:px-16">
      <Link
        to="/"
        aria-label="返回 Aerie 首页"
        className="liquid-glass flex h-12 w-12 items-center justify-center rounded-full"
        onClick={close}
      >
        <img src="/aerie-logo.svg" alt="Aerie · 云栖" className="h-8 w-8 object-contain" />
      </Link>

      <nav className="liquid-glass hidden items-center rounded-full px-1.5 py-1.5 md:flex">
        {navigation.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              `rounded-full px-3 py-2 text-sm font-medium font-body transition-colors ${
                isActive ? 'bg-white/15 text-white' : 'text-white/70 hover:text-white'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
        <a
          href={release.url}
          download={release.filename}
          className="ml-1 flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-sm font-medium text-black font-body"
        >
          获取便携版
          <ArrowUpRight className="h-4 w-4" />
        </a>
      </nav>

      <button
        type="button"
        aria-label={open ? '关闭导航菜单' : '打开导航菜单'}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="liquid-glass flex h-12 w-12 flex-col items-center justify-center gap-1.5 rounded-full md:hidden"
      >
        <span className={`h-px w-4 bg-white transition-transform ${open ? 'translate-y-[3.5px] rotate-45' : ''}`} />
        <span className={`h-px w-4 bg-white transition-transform ${open ? '-translate-y-[3.5px] -rotate-45' : ''}`} />
      </button>
      <div className="hidden h-12 w-12 md:block" />

      {open && (
        <nav className="liquid-glass absolute left-5 right-5 top-16 flex flex-col rounded-[1.25rem] p-2 md:hidden">
          {navigation.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={close}
              className={`rounded-xl px-4 py-3 text-sm font-medium ${
                location.pathname === item.path ? 'bg-white/15 text-white' : 'text-white/75'
              }`}
            >
              {item.label}
            </NavLink>
          ))}
          <a
            href={release.url}
            download={release.filename}
            className="mt-1 flex items-center justify-between rounded-xl bg-white px-4 py-3 text-sm font-medium text-black"
          >
            获取便携版
            <ArrowUpRight className="h-4 w-4" />
          </a>
        </nav>
      )}
    </header>
  )
}
