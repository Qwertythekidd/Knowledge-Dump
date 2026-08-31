import type { SVGProps } from "react";

type Props = SVGProps<SVGSVGElement>;

function Icon({ children, ...props }: Props) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{children}</svg>;
}

export const CloudIcon = (props: Props) => <Icon {...props}><path d="M6.5 18.5h11a4 4 0 0 0 .8-7.92A6.5 6.5 0 0 0 5.9 8.3a5.2 5.2 0 0 0 .6 10.2Z" /><path d="m9 14 3-3 3 3M12 11v7" /></Icon>;
export const FolderIcon = (props: Props) => <Icon {...props}><path d="M3.5 6.5h6l2 2H20a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 20 19.5H4A1.5 1.5 0 0 1 2.5 18V8a1.5 1.5 0 0 1 1-1.5Z" /></Icon>;
export const FileIcon = (props: Props) => <Icon {...props}><path d="M6 2.5h8l4 4v15H6z" /><path d="M14 2.5v5h4M9 13h6M9 17h6" /></Icon>;
export const ImageIcon = (props: Props) => <Icon {...props}><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8.5" cy="9" r="1.5" /><path d="m4 17 5-5 3 3 2-2 6 6" /></Icon>;
export const ArchiveIcon = (props: Props) => <Icon {...props}><path d="M4 7h16v14H4zM3 3h18v4H3zM9 11h6" /></Icon>;
export const ActivityIcon = (props: Props) => <Icon {...props}><path d="M3 12h4l2-6 4 12 2-6h6" /></Icon>;
export const SettingsIcon = (props: Props) => <Icon {...props}><circle cx="12" cy="12" r="3" /><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1A7 7 0 0 0 15 6l-.3-2.5h-4L10.4 6A7 7 0 0 0 9 7.1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.4.8l.3 2.8h4l.3-2.8a7 7 0 0 0 1.5-.8l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1Z" /></Icon>;
export const SearchIcon = (props: Props) => <Icon {...props}><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" /></Icon>;
export const UploadIcon = (props: Props) => <Icon {...props}><path d="M12 16V4M7 9l5-5 5 5M4 20h16" /></Icon>;
export const DownloadIcon = (props: Props) => <Icon {...props}><path d="M12 4v12M7 11l5 5 5-5M4 20h16" /></Icon>;
export const MoreIcon = (props: Props) => <Icon {...props}><circle cx="5" cy="12" r="1" fill="currentColor" /><circle cx="12" cy="12" r="1" fill="currentColor" /><circle cx="19" cy="12" r="1" fill="currentColor" /></Icon>;
export const GridIcon = (props: Props) => <Icon {...props}><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /></Icon>;
export const ListIcon = (props: Props) => <Icon {...props}><path d="M8 6h13M8 12h13M8 18h13" /><circle cx="3" cy="6" r="1" fill="currentColor" /><circle cx="3" cy="12" r="1" fill="currentColor" /><circle cx="3" cy="18" r="1" fill="currentColor" /></Icon>;
export const CloseIcon = (props: Props) => <Icon {...props}><path d="m5 5 14 14M19 5 5 19" /></Icon>;
export const CheckIcon = (props: Props) => <Icon {...props}><path d="m5 12 4 4L19 6" /></Icon>;
