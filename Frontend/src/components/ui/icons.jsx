/**
 * Shared icon module.
 * Thin re-export layer over @phosphor-icons/react — every icon defaults to weight="bold".
 * Drop-in replacement for lucide-react imports.
 *
 * Usage:  import { Users, Search } from "../ui/icons";
 *         <Users size={18} />
 */
import { createElement } from "react";
import * as P from "@phosphor-icons/react";

const Cx = (Icon) => (props) =>
  createElement(Icon, { weight: "bold", ...props });

// ── Navigation & Structure ─────────────────────────
export const LayoutDashboard = Cx(P.GridNine);
export const PlayCircle = Cx(P.PlayCircle);
export const Users = Cx(P.Users);
export const BookOpen = Cx(P.BookOpen);
export const Store = Cx(P.Storefront);
export const Storefront = Cx(P.Storefront);
export const ShoppingBag = Cx(P.ShoppingBag);
export const MusicNote = Cx(P.MusicNote);
export const FilmSlate = Cx(P.FilmSlate);
export const ShoppingCart = Cx(P.ShoppingCart);
export const CreditCard = Cx(P.CreditCard);
export const History = Cx(P.Clock);
export const DollarSign = Cx(P.CurrencyDollar);
export const AlertOctagon = Cx(P.WarningOctagon);
export const RefreshCw = Cx(P.ArrowClockwise);
export const BarChart3 = Cx(P.ChartBar);
export const ClipboardList = Cx(P.ClipboardText);
export const Trash2 = Cx(P.Trash);
export const Brain = Cx(P.Brain);
export const GitBranch = Cx(P.GitBranch);
export const ChevronLeft = Cx(P.CaretLeft);
export const ChevronRight = Cx(P.CaretRight);
export const Activity = Cx(P.ActivityIcon);
export const Layers = Cx(P.Stack);
export const Repeat = Cx(P.Repeat);
export const TrendingUp = Cx(P.TrendUp);
export const TrendingDown = Cx(P.TrendDown);
export const ExternalLink = Cx(P.ArrowSquareOut);
export const AlertTriangle = Cx(P.Warning);
export const CheckCircle2 = Cx(P.CheckCircle);
export const XCircle = Cx(P.XCircle);
export const PauseCircle = Cx(P.PauseCircle);
export const X = Cx(P.X);
export const Pause = Cx(P.Pause);
export const Play = Cx(P.Play);

// ── Actions ────────────────────────────────────────
export const Search = Cx(P.MagnifyingGlass);
export const Filter = Cx(P.Faders);
export const Faders = Cx(P.Faders);
export const Zap = Cx(P.Lightning);
export const ShieldCheck = Cx(P.ShieldCheck);
export const Shield = Cx(P.Shield);
export const FileText = Cx(P.File);
export const Inbox = Cx(P.FileText);
export const Send = Cx(P.PaperPlane);
export const Calendar = Cx(P.Calendar);
export const Clock = Cx(P.Clock);

// ── Table & Schema ─────────────────────────────────
export const Database = Cx(P.Database);
export const Table = Cx(P.Table);
export const Key = Cx(P.Key);
export const Hash = Cx(P.Hash);
export const Check = Cx(P.Check);
export const Minus = Cx(P.Minus);
export const Plus = Cx(P.Plus);
export const Copy = Cx(P.Copy);
export const ArrowDownLeft = Cx(P.ArrowDownLeft);
export const ArrowUpRight = Cx(P.ArrowUpRight);
export const PieChart = Cx(P.ChartPie);
export const Landmark = Cx(P.Bank);
export const Percent = Cx(P.Percent);
export const Wallet = Cx(P.Wallet);
export const User = Cx(P.User);
export const AlertCircle = Cx(P.WarningCircle);
export const ChevronDown = Cx(P.CaretDown);
