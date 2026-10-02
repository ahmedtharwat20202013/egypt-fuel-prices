# Egypt Fuel Prices Auto Updater

ملف بيانات عام ومحدّث آليًا لأسعار الوقود في مصر، مصدره صفحات **وزارة البترول والثروة المعدنية المصرية** فقط. يمكن لتطبيق Android قراءة `prices.json` مباشرة دون إصدار تحديث جديد للتطبيق عند تغيّر الأسعار.

## الروابط

- Repository: https://github.com/ahmedtharwat20202013/egypt-fuel-prices
- Raw JSON: https://raw.githubusercontent.com/ahmedtharwat20202013/egypt-fuel-prices/main/prices.json
- المصدر الأساسي: https://www.petroleum.gov.eg/ar-eg/Pages/HomePage.aspx
- بيان الوزارة المستخدم لإثبات سعر CNG: https://www.petroleum.gov.eg/ar-eg/media-center/news/news-pages/Pages/mop_10032026_02.aspx

## البيانات الحالية

| المفتاح | المنتج | السعر | الوحدة |
|---|---|---:|---|
| `gasoline_80` | بنزين 80 | 20.75 | جنيه/لتر |
| `gasoline_92` | بنزين 92 | 22.25 | جنيه/لتر |
| `gasoline_95` | بنزين 95 | 24 | جنيه/لتر |
| `diesel` | سولار | 20.5 | جنيه/لتر |
| `cng` | غاز تموين السيارات | 13 | جنيه/م³ |

## Schema

```json
{
  "country": "EG",
  "currency": "EGP",
  "unit": "liter",
  "source": { "name": "Egyptian Ministry of Petroleum and Mineral Resources", "url": "..." },
  "lastUpdated": "YYYY-MM-DD",
  "fetchedAt": "ISO-8601",
  "prices": {
    "gasoline_80": 0,
    "gasoline_92": 0,
    "gasoline_95": 0,
    "diesel": 0,
    "cng": 0
  }
}
```

> ملاحظة: `cng` سعره لكل متر مكعب وفق بيان الوزارة، بينما بقية المنتجات السائلة سعرها لكل لتر.

## التحديث التلقائي

GitHub Actions يعمل تلقائيًا كل 12 ساعة عند الدقيقة 17 (`17 */12 * * *`)، ويمكن تشغيله يدويًا من [صفحة Actions](https://github.com/ahmedtharwat20202013/egypt-fuel-prices/actions) عبر **Run workflow**.

كل تشغيل يقوم بتحميل صفحات الوزارة، واستخراج المنتجات الخمسة المستخدمة في التطبيق، ثم تنفيذ Validation قبل الكتابة. يتم إنشاء Commit فقط إذا تغيّرت الأسعار.

## Validation وFail-Safe

- الصفحة الرسمية يجب أن تكون متاحة وناجحة HTTP وغير فارغة.
- المنتجات الستة إلزامية؛ غياب أي منتج أو تغيّر بنية الصفحة يؤدي إلى فشل الـWorkflow.
- الأسعار أرقام موجبة داخل نطاق منطقي، مع دعم الأرقام العربية والإنجليزية والفواصل.
- لا يوجد حد نسبي للتغيير؛ السعر الجديد يُقبل إذا كان رقمًا موجبًا داخل النطاق المنطقي وتم استخراجه من المصدر الرسمي.
- الكتابة تتم ذريًا ولا تتم إلا بعد نجاح جميع الفحوص.
- عند timeout أو HTTP error أو parsing error أو validation failure، يبقى آخر `prices.json` صحيح كما هو، ويفشل الـWorkflow بدل نشر بيانات ناقصة أو مخمّنة.

## تشغيل محلي

```bash
python -m pip install -r requirements.txt
python scripts/update_prices.py
pytest -q
```

اختبارات Fail-Safe تحاكي غياب منتج وسعرًا غير صالح دون إفساد ملف الإنتاج.

## استخدام JSON في التطبيق

```javascript
const response = await fetch(
  "https://raw.githubusercontent.com/ahmedtharwat20202013/egypt-fuel-prices/main/prices.json",
  { cache: "no-store" }
);

if (!response.ok) {
  throw new Error("Failed to load fuel prices");
}

const data = await response.json();
console.log(data.prices.gasoline_92);
```

لا يعتمد المشروع على Facebook أو الأخبار أو Google snippets أو مواقع التجميع كمصدر نشر نهائي؛ أي قيمة غير قابلة للتحقق من نطاق الوزارة لا تُنشر.
