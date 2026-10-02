# Egypt Fuel Prices Auto Updater

تحديث تلقائي لأسعار الوقود في مصر من صفحة وزارة البترول والثروة المعدنية.

## المصدر الرسمي

https://www.petroleum.gov.eg/ar-eg/Pages/HomePage.aspx?ItemID=719

## الملفات

```text
.
├── prices.json
├── requirements.txt
├── scripts/
│   └── update_prices.py
└── .github/
    └── workflows/
        └── update-prices.yml
```

## ماذا يحدث تلقائيًا؟

GitHub Actions يعمل كل 12 ساعة، ويقوم بـ:

1. تحميل صفحة وزارة البترول.
2. استخراج بنزين 80 و92 و95 والسولار والكيروسين وغاز تموين السيارات.
3. التحقق من وجود كل الأسعار.
4. التحقق أن القيم أرقام وفي نطاق منطقي.
5. رفض التحديث إذا حدث تغير مفاجئ جدًا أو تغير شكل المصدر بطريقة غير متوقعة.
6. تعديل `prices.json` فقط عند وجود تغيير.
7. عمل Commit تلقائي.

## تشغيل يدوي

من GitHub:

Actions → Update Egypt Fuel Prices → Run workflow

## استخدام الملف داخل التطبيق

بعد رفع الـ repository، استخدم رابط Raw لملف:

```text
https://raw.githubusercontent.com/USERNAME/REPOSITORY/main/prices.json
```

مثال JavaScript:

```js
const response = await fetch(
  "https://raw.githubusercontent.com/USERNAME/REPOSITORY/main/prices.json",
  { cache: "no-store" }
);

if (!response.ok) {
  throw new Error("Failed to load fuel prices");
}

const data = await response.json();

const price92 = data.prices.gasoline_92;
```

## مهم

هذا المشروع لا يعتبر الأخبار أو مواقع التواصل مصدرًا للأسعار. المصدر المحدد في الكود هو موقع وزارة البترول والثروة المعدنية.

لو الوزارة غيرت تصميم الصفحة، الـ workflow يفشل ولا يكتب بيانات جديدة، وده مقصود لحماية التطبيق من نشر سعر خاطئ.
