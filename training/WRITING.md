# Rapor yazma rehberi

Her dosya `training/labels/` altında. Kutudaki istatistiklere bak, altındaki
taslağı iyi bir koçun söyleyeceği şekilde yeniden yaz, en üstteki satırda
`status: draft` yerine `status: done` yaz. Sonra kontrol et:

```bash
cd ~/Desktop/projects/FeelFit/forge-coach
.venv/bin/python -m training.label check
```

## Kurallar

1. **Rakamlar sadece kutudan gelir.** Yeni yüzde, toplam ya da ortalama
   hesaplama. Serbest olanlar: 0–10 arası sayılar ("iki antrenman"), 2,5 / 5 /
   7,5 kg plaka artışları. `check` uydurma rakamı yakalar.
2. **Her liste en fazla 3 madde**, her madde tek ve sade bir cümle.
3. **Kullanıcıyla konuş**: İngilizcede "you", Türkçede "sen". Sıcak ama net.
4. **Bu veriye özel ol.** "Su içmeyi unutma" gibi genel tavsiye yok.
5. **Takılan hareket varsa tek somut değişiklik öner**: tekrar aralığı, yük ya
   da sıklık.
6. **Bu hafta devam ediyor.** Haftanın başında az antrenman normaldir, suçlama.
7. **Tıbbi, sakatlık, diyet tavsiyesi yok; kiloya ya da görünüşe yorum yok.**
8. **Ton** dördünden biri:
   - `celebrate`: rekor ya da belirgin ilerleme
   - `steady`: yolunda
   - `nudge`: geçen hafta planlanandan az, daha önce düzenliyken
   - `welcome`: geçmiş yok ya da çok az

Hareket adlarını kutudaki gibi bırak (Türkçe raporda da "Barbell Squat").
Türkçede ondalık için virgül kullan: 62,5 kg. Binlik ayırıcı koyma: 8730 kg.

## Örnek: s0004-en (takılan hareketler)

Taslak (kural koçu):

> **headline:** 1 sessions so far this week, 8730 kg lifted.
> **wins:** 6 weeks in a row with at least one session.
> **focus:** Incline Dumbbell Press has not improved for 5 weeks (best estimate 40 kg). / Barbell Row has not improved for 5 weeks (best estimate 110.8 kg).
> **next:** For Incline Dumbbell Press, switch to a new rep range... / Plan 2 sessions...

Daha iyi hali (`check`ten geçiyor):

```
## headline
Steady week so far: one session in, and you are on pace for your two.

## wins
- Six weeks in a row with at least one session. That consistency is what makes progress possible.
- One of your two planned sessions is already done with half the week left.

## focus_areas
- Four lifts have not moved in a month or more: Incline Dumbbell Press, Barbell Row and Overhead Press for 5 weeks, Barbell Bench Press for 4.
- When everything stalls at once, the plan needs a change more than extra effort.

## next_week
- Take a lighter week: same lifts, about half the sets, and stop well short of failure.
- After that, move Incline Dumbbell Press and Overhead Press to 8 to 10 reps for the next 3 weeks.
- Keep both sessions on the calendar so the streak reaches 7 weeks.

## tone
steady
```

Farkı: taslak tek tek hareketleri sayıyor; iyi rapor dört hareketin birden
takıldığını görüp asıl sorunu (program değişmeli) söylüyor, haftanın yarısında
olunduğunu hesaba katıyor ve sırayla uygulanacak bir plan veriyor.
