import { redirect } from "next/navigation";

// Chat is the whole app; the root path is just a doorway to it.
export default function Home() {
  redirect("/chat");
}
