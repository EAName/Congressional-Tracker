import { redirect } from "next/navigation";

export default async function LegacyRaceRedirect({
  params,
}: {
  params: Promise<{ raceId: string }>;
}) {
  const { raceId } = await params;
  redirect(`/race/${raceId}`);
}
