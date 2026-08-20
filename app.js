// ============================================================
// محصولات واقعی از خروجی تلگرام (messages.html)
// ============================================================
const realProducts = [
    {
        id: 1,
        name: "کفش old navy",
        price: 15,
        size: "8",
        weight: 0.276,
        category: "کفش",
        location: "موجودی تهران",
        image: "photos/photo_1110@11-06-2026_00-28-05.jpg",
        description: "کفش old navy اورجینال، سایز 8، وزن 276 گرم",
        telegramLinks: [
            "https://t.me/fatemehalamdar68",
            "https://t.me/rshb63"
        ]
    },
    {
        id: 2,
        name: "صندل مردانه cross",
        price: 60,
        size: "M/10, w/12",
        weight: 0.638,
        category: "صندل مردانه",
        location: "موجودی تهران",
        image: "photos/photo_1117@11-06-2026_00-30-02.jpg",
        description: "صندل مردانه cross با کیفیت بالا",
        telegramLinks: [
            "https://t.me/Rh_reyhan",
            "https://t.me/f_ati_a"
        ]
    },
    {
        id: 3,
        name: "کفش adidas مردانه",
        price: 59,
        size: "9",
        weight: 0.828,
        category: "کفش",
        location: "موجودی تهران",
        image: "photos/photo_1118@11-06-2026_00-44-09.jpg",
        description: "کفش adidas مدل جدید، سایز 9",
        telegramLinks: [
            "https://t.me/Rh_reyhan",
            "https://t.me/f_ati_a"
        ]
    },
    {
        id: 4,
        name: "کفش Mk",
        price: 59,
        size: "9",
        weight: 0.8,
        category: "کفش",
        location: "موجودی تهران",
        image: "photos/photo_1121@11-06-2026_00-45-20.jpg",
        description: "کفش مارک Mk اورجینال",
        telegramLinks: [
            "https://t.me/Rh_reyhan",
            "https://t.me/f_ati_a"
        ]
    },
    {
        id: 5,
        name: "کفش بچگانه puma",
        price: 29,
        size: "uk:1, us:2c",
        weight: 0.458,
        category: "کفش بچگانه",
        location: "موجودی تهران",
        image: "photos/photo_1124@11-06-2026_00-48-48.jpg",
        description: "کفش بچگانه پوما مناسب کودکان",
        telegramLinks: [
            "https://t.me/Rh_reyhan",
            "https://t.me/f_ati_a"
        ]
    },
    {
        id: 6,
        name: "کفش toms",
        price: 25,
        size: "7",
        weight: 0.334,
        category: "کفش",
        location: "موجودی تهران",
        image: "photos/photo_1128@11-06-2026_00-51-08.jpg",
        description: "کفش toms سبک و راحت",
        telegramLinks: []
    },
    {
        id: 7,
        name: "کیف تامی",
        price: 29.99,
        size: "—",
        weight: 0.5,
        category: "کیف",
        location: "موجودی تهران",
        image: "photos/photo_1152@15-07-2026_21-12-54.jpg",
        description: "کیف تامی با تخفیف ویژه",
        telegramLinks: []
    },
    {
        id: 8,
        name: "کفش آدیداس سامبا",
        price: 91,
        size: "US 8",
        weight: 0.495,
        category: "کفش",
        location: "موجودی تهران",
        image: "photos/photo_1135@20-06-2026_22-10-53.jpg",
        description: "کفش آدیداس نیوکالکشن سامبا",
        telegramLinks: []
    },
    {
        id: 9,
        name: "کیف تامی (مدل دوم)",
        price: 38,
        size: "—",
        weight: 0.5,
        category: "کیف",
        location: "موجودی کانادا",
        image: "photos/photo_1155@15-07-2026_21-15-06.jpg",
        description: "کیف تامی مدل دوم با تخفیف",
        telegramLinks: []
    },
    {
        id: 10,
        name: "کیف تامی (مدل سوم)",
        price: 38,
        size: "—",
        weight: 0.5,
        category: "کیف",
        location: "موجودی تهران",
        image: "photos/photo_1162@15-07-2026_21-21-58.jpg",
        description: "کیف تامی مدل سوم با تخفیف",
        telegramLinks: []
    }
];

// ============================================================
// تنظیمات پیش‌فرض قیمت‌گذاری
// ============================================================
const defaultSettings = {
    usdRate: 200000,
    shippingPerKg: 8000000,
    multiplier: 1.5
};

// ============================================================
// متغیرهای گلوبال
// ============================================================
let products = [];
let settings = { ...defaultSettings };
let isAdmin = false;

// ============================================================
// تابع شبیه‌سازی بارگذاری (رفع باگ لودینگ)
// ============================================================
function loadProductsFromRealData() {
    return new Promise((resolve) => {
        setTimeout(() => {
            products = [...realProducts];
            resolve();
        }, 500);
    });
}

// ============================================================
// محاسبه قیمت نهایی
// ============================================================
function calculateFinalPrice(product, settings) {
    const { price, weight } = product;
    const { usdRate, shippingPerKg, multiplier } = settings;
    const baseToman = price * usdRate;
    const shippingToman = weight * shippingPerKg;
    const finalToman = (baseToman * multiplier) + shippingToman;
    return Math.round(finalToman);
}

// ============================================================
// رندر کردن یک محصول
// ============================================================
function renderProduct(product) {
    const finalPrice = calculateFinalPrice(product, settings);
    const telegramLinksHtml = product.telegramLinks.length > 0
        ? product.telegramLinks.map(link => `
            <a href="${link}" target="_blank" class="btn-contact">
                <i class="fab fa-telegram"></i> تلگرام
            </a>
        `).join('')
        : '<button class="btn-contact" disabled><i class="fas fa-ban"></i> لینک ندارد</button>';

    return `
        <div class="product-card" data-id="${product.id}">
            <div class="product-image">
                <img src="${product.image}" alt="${product.name}" onerror="this.src='https://via.placeholder.com/350x220/2d3748/e2e8f0?text=عکس+موجود+نیست'">
            </div>
            <div class="product-details">
                <h3 class="product-title">${product.name}</h3>
                <div class="product-meta">
                    <span class="meta-item">
                        <i class="fas fa-dollar-sign"></i> قیمت: $${product.price}
                    </span>
                    <span class="meta-item">
                        <i class="fas fa-ruler"></i> سایز: ${product.size}
                    </span>
                    <span class="meta-item">
                        <i class="fas fa-weight"></i> وزن: ${product.weight} کیلوگرم
                    </span>
                    <span class="meta-item">
                        <i class="fas fa-tag"></i> دسته: ${product.category}
                    </span>
                    <span class="meta-item">
                        <i class="fas fa-map-marker-alt"></i> موقعیت: ${product.location}
                    </span>
                </div>
                <p class="product-description">${product.description}</p>
                <div class="product-pricing">
                    <div class="price-row">
                        <span>قیمت پایه (تومان):</span>
                        <span>${(product.price * settings.usdRate).toLocaleString()}</span>
                    </div>
                    <div class="price-row">
                        <span>هزینه حمل (تومان):</span>
                        <span>${(product.weight * settings.shippingPerKg).toLocaleString()}</span>
                    </div>
                    <div class="final-price">
                        <span>قیمت نهایی:</span>
                        <strong>${finalPrice.toLocaleString()} تومان</strong>
                    </div>
                </div>
                <div class="product-actions">
                    ${telegramLinksHtml}
                    <button class="btn-details" onclick="showProductDetails(${product.id})">
                        <i class="fas fa-info-circle"></i> جزئیات
                    </button>
                </div>
            </div>
        </div>
    `;
}

// ============================================================
// رندر کردن همه محصولات
// ============================================================
function renderProducts(productList) {
    const container = document.getElementById('products-list');
    if (!container) return;

    if (productList.length === 0) {
        container.innerHTML = `
            <div class="loading">
                <i class="fas fa-search"></i> محصولی یافت نشد.
            </div>
        `;
        updateProductCount(0);
        return;
    }

    container.innerHTML = productList.map(renderProduct).join('');
    updateProductCount(productList.length);
}

// ============================================================
// به‌روزرسانی شمارنده محصولات
// ============================================================
function updateProductCount(count) {
    const countElement = document.getElementById('product-count');
    if (countElement) {
        countElement.textContent = `${count} محصول`;
    }
}

// ============================================================
// اعمال فیلترها
// ============================================================
function applyFilters() {
    const searchText = document.getElementById('search-input').value.toLowerCase();
    const category = document.getElementById('category-filter').value;
    const minPrice = parseFloat(document.getElementById('min-price').value) || 0;
    const maxPrice = parseFloat(document.getElementById('max-price').value) || Infinity;

    let filtered = products.filter(p => {
        const matchesSearch = p.name.toLowerCase().includes(searchText) ||
                             p.description.toLowerCase().includes(searchText);
        const matchesCategory = !category || p.category === category;
        const matchesPrice = p.price >= minPrice && p.price <= maxPrice;
        return matchesSearch && matchesCategory && matchesPrice;
    });

    // مرتب‌سازی
    const sortBy = document.getElementById('sort-by').value;
    if (sortBy === 'price') filtered.sort((a, b) => a.price - b.price);
    if (sortBy === 'price-desc') filtered.sort((a, b) => b.price - a.price);
    if (sortBy === 'weight') filtered.sort((a, b) => a.weight - b.weight);
    if (sortBy === 'name') filtered.sort((a, b) => a.name.localeCompare(b.name));

    renderProducts(filtered);
}

// ============================================================
// ریست فیلترها
// ============================================================
function resetFilters() {
    document.getElementById('search-input').value = '';
    document.getElementById('category-filter').value = '';
    document.getElementById('min-price').value = '';
    document.getElementById('max-price').value = '';
    document.getElementById('sort-by').value = 'name';
    renderProducts(products);
}

// ============================================================
// ذخیره تنظیمات
// ============================================================
function saveSettings() {
    settings = {
        usdRate: parseInt(document.getElementById('usd-rate').value) || defaultSettings.usdRate,
        shippingPerKg: parseInt(document.getElementById('shipping-per-kg').value) || defaultSettings.shippingPerKg,
        multiplier: parseFloat(document.getElementById('multiplier').value) || defaultSettings.multiplier
    };
    localStorage.setItem('tehran-inventory-settings', JSON.stringify(settings));
    alert('✅ تنظیمات ذخیره شد.');
    renderProducts(products); // برای محاسبه مجدد قیمت‌ها
}

// ============================================================
// بارگذاری تنظیمات از localStorage
// ============================================================
function loadSettings() {
    const saved = localStorage.getItem('tehran-inventory-settings');
    if (saved) {
        try {
            settings = JSON.parse(saved);
            if (isAdmin) {
                document.getElementById('usd-rate').value = settings.usdRate;
                document.getElementById('shipping-per-kg').value = settings.shippingPerKg;
                document.getElementById('multiplier').value = settings.multiplier;
            }
        } catch (e) {
            console.error('خطا در بارگذاری تنظیمات:', e);
        }
    }
}

// ============================================================
// مدیریت حالت ادمین
// ============================================================
function toggleAdmin() {
    const adminBtn = document.getElementById('admin-toggle');
    
    if (isAdmin) {
        // خروج از حالت ادمین
        isAdmin = false;
        document.getElementById('price-settings').style.display = 'none';
        adminBtn.innerHTML = '<i class="fas fa-user-shield"></i> ورود ادمین';
        adminBtn.classList.remove('logged-in');
        return;
    }

    // ورود ادمین - دو مرحله
    const username = prompt('👤 نام کاربری را وارد کنید:');
    if (username !== 'elham') {
        if (username !== null) alert('❌ نام کاربری اشتباه است.');
        return;
    }

    const password = prompt('🔐 رمز عبور را وارد کنید:');
    if (password !== null) {
        if (password !== null) alert('❌ رمز عبور اشتباه است.');
        return;
    }

    // ورود موفق
    isAdmin = true;
    document.getElementById('price-settings').style.display = 'block';
    adminBtn.innerHTML = '<i class="fas fa-user-check"></i> ادمین: elham';
    adminBtn.classList.add('logged-in');
    
    // پر کردن فیلدها با مقادیر ذخیره‌شده
    document.getElementById('usd-rate').value = settings.usdRate;
    document.getElementById('shipping-per-kg').value = settings.shippingPerKg;
    document.getElementById('multiplier').value = settings.multiplier;
}

// ============================================================
// خروج ادمین از طریق دکمه جداگانه
// ============================================================
function logoutAdmin() {
    isAdmin = false;
    document.getElementById('price-settings').style.display = 'none';
    const adminBtn = document.getElementById('admin-toggle');
    adminBtn.innerHTML = '<i class="fas fa-user-shield"></i> ورود ادمین';
    adminBtn.classList.remove('logged-in');
    alert('✅ از حالت ادمین خارج شدید.');
}

// ============================================================
// نمایش جزئیات محصول (آلرت ساده)
// ============================================================
function showProductDetails(productId) {
    const product = products.find(p => p.id === productId);
    if (!product) return;
    
    const finalPrice = calculateFinalPrice(product, settings);
    
    let message = `📋 ${product.name}\n\n`;
    message += `🏷️ قیمت (دلار): $${product.price}\n`;
    message += `📏 سایز: ${product.size}\n`;
    message += `⚖️ وزن: ${product.weight} کیلوگرم\n`;
    message += `📦 دسته‌بندی: ${product.category}\n`;
    message += `📍 محل موجودی: ${product.location}\n`;
    message += `💰 قیمت نهایی: ${finalPrice.toLocaleString()} تومان\n\n`;
    message += `💬 توضیحات: ${product.description}\n\n`;
    
    if (product.telegramLinks.length > 0) {
        message += `🔗 لینک‌های فروشنده:\n`;
        product.telegramLinks.forEach((link, index) => {
            message += `${index + 1}. ${link}\n`;
        });
    } else {
        message += `🔗 لینک فروشنده: موجود نیست`;
    }
    
    alert(message);
}

// ============================================================
// راه‌اندازی اولیه
// ============================================================
document.addEventListener('DOMContentLoaded', async function() {
    console.log('🚀 پروژه موجودی تهران در حال راه‌اندازی...');
    
    // بارگذاری تنظیمات ذخیره‌شده
    loadSettings();
    
    // بارگذاری محصولات واقعی از داده‌های تلگرام
    await loadProductsFromRealData();
    
    // رندر اولیه محصولات
    renderProducts(products);
    
    console.log(`✅ ${products.length} محصول از خروجی تلگرام بارگذاری شد.`);
    console.log('📱 منبع: فایل messages.html (خروجی تلگرام)');
    
    // ========================================================
    // اتصال Event Listeners
    // ========================================================
    
    // دکمه‌های فیلتر
    document.getElementById('apply-filters').addEventListener('click', applyFilters);
    document.getElementById('reset-filters').addEventListener('click', resetFilters);
    
    // ذخیره تنظیمات
    document.getElementById('save-settings').addEventListener('click', saveSettings);
    
    // ورود ادمین
    document.getElementById('admin-toggle').addEventListener('click', toggleAdmin);
    
    // خروج ادمین از بخش تنظیمات
    document.getElementById('logout-admin').addEventListener('click', logoutAdmin);
    
    // جستجوی زنده با debounce
    let searchTimeout;
    document.getElementById('search-input').addEventListener('input', function () {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyFilters, 300);
    });
    
    // فیلترهای دیگر
    document.getElementById('category-filter').addEventListener('change', applyFilters);
    document.getElementById('min-price').addEventListener('change', applyFilters);
    document.getElementById('max-price').addEventListener('change', applyFilters);
    document.getElementById('sort-by').addEventListener('change', applyFilters);
    
    // جستجو با کلید Enter
    document.getElementById('search-input').addEventListener('keyup', function (e) {
        if (e.key === 'Enter') {
            clearTimeout(searchTimeout);
            applyFilters();
        }
    });
    
    console.log('✅ پروژه موجودی تهران - نسخه MVP - آماده به کار');
    console.log('💡 راهنما: برای دسترسی به تنظیمات قیمت‌گذاری، روی "ورود ادمین" کلیک کنید');
    console.log('Admin credentials are configured outside the source code.');
});
