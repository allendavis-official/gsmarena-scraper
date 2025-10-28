import requests
from bs4 import BeautifulSoup
import json
import time
import csv
import os
import re
from urllib.parse import urljoin, urlparse
from pathlib import Path

def sanitize_filename(filename):
    """
    Sanitize filename to remove invalid characters and clean up the name
    """
    # Remove review text and other unwanted phrases
    filename = re.sub(r'\s*(?:hands-on\s*)?review\s*', ' ', filename, flags=re.IGNORECASE)
    filename = re.sub(r'\s*&\s*', ' and ', filename)
    
    # Remove or replace invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    # Remove extra spaces and clean up
    filename = re.sub(r'\s+', ' ', filename).strip()
    
    # Remove leading/trailing spaces and dots
    filename = filename.strip('. ')
    
    # Limit length
    if len(filename) > 100:
        filename = filename[:100]
    
    return filename

def clean_phone_name(phone_name):
    """
    Extract a clean phone name for folder and file naming
    """
    # Remove review text
    clean_name = re.sub(r'\s*(?:hands-on\s*)?review\s*', '', phone_name, flags=re.IGNORECASE)
    
    # Remove anything in parentheses
    clean_name = re.sub(r'\([^)]*\)', '', clean_name)
    
    # Remove extra spaces and special characters
    clean_name = re.sub(r'[&]', 'and', clean_name)
    clean_name = re.sub(r'[^\w\s-]', '', clean_name)
    clean_name = re.sub(r'\s+', ' ', clean_name).strip()
    
    # Common brand mappings for consistency
    brand_mappings = {
        'xiaomi': 'Xiaomi',
        'samsung': 'Samsung',
        'vivo': 'vivo',
        'oneplus': 'OnePlus',
        'google': 'Google',
        'apple': 'Apple',
        'iphone': 'iPhone'
    }
    
    # Extract brand and model
    words = clean_name.split()
    if words and words[0].lower() in brand_mappings:
        brand = brand_mappings[words[0].lower()]
        model = ' '.join(words[1:])
    else:
        brand = words[0] if words else 'Unknown'
        model = ' '.join(words[1:])
    
    # Create a clean display name
    display_name = f"{brand} {model}" if model else brand
    
    return {
        'safe_name': sanitize_filename(clean_name),
        'display_name': display_name,
        'brand': brand,
        'model': model
    }

def download_image(image_url, save_path, headers):
    """
    Download a single image from URL and save to disk
    """
    try:
        response = requests.get(image_url, headers=headers, timeout=15, stream=True)
        response.raise_for_status()
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # Save image
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Verify the file was created and has content
        if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
            return True
        else:
            return False
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error {e.response.status_code}")
        return False
    except Exception as e:
        print(f"Error: {str(e)[:50]}")
        return False

def construct_pictures_url(spec_url):
    """
    Construct pictures URL from specification URL
    Pattern: vivo_x300_pro_5g-14225.php -> vivo_x300_pro_5g-pictures-14225.php
    """
    try:
        # Remove the domain if present
        if 'gsmarena.com/' in spec_url:
            spec_url = spec_url.split('gsmarena.com/')[-1]
        
        # Remove .php extension
        base = spec_url.replace('.php', '')
        
        # Split by last dash to separate name and ID
        parts = base.rsplit('-', 1)
        
        if len(parts) == 2:
            phone_name = parts[0]
            phone_id = parts[1]
            pictures_url = f"https://www.gsmarena.com/{phone_name}-pictures-{phone_id}.php"
            return pictures_url
        
        return None
    except Exception as e:
        print(f"      ✗ Error constructing URL: {e}")
        return None

def scrape_images_from_pictures_page(pictures_url, headers, max_images=5):
    """
    Scrape image URLs from the pictures page
    Looks specifically in the #pictures-list div and specs-photo-main div
    """
    try:
        response = requests.get(pictures_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        image_urls = []
        
        # First, look for the main image in specs-photo-main div
        print(f"      Looking for main image in specs-photo-main...")
        specs_photo_main = soup.find('div', class_='specs-photo-main')
        if specs_photo_main:
            img_tag = specs_photo_main.find('img')
            if img_tag and img_tag.get('src'):
                main_img_src = img_tag['src']
                # Make absolute URL
                main_img_url = urljoin('https://www.gsmarena.com/', main_img_src)
                
                # Try to get larger version if it's a thumbnail
                if '/vv/bigpic/' in main_img_url or '/vv/pics/' in main_img_url:
                    # Already a good quality image
                    pass
                elif 'thumb' in main_img_url.lower():
                    # Try to convert thumbnail to full size
                    main_img_url = main_img_url.replace('thumb', 'pics')
                
                if main_img_url not in image_urls:
                    image_urls.append(main_img_url)
                    print(f"      ✓ Found main image in specs-photo-main")
        
        # Then look for the pictures-list div
        pictures_list = soup.find('div', id='pictures-list')
        
        if pictures_list:
            # Find all image links within pictures-list
            links = pictures_list.find_all('a', href=True)
            
            for link in links:
                href = link['href']
                
                # GSMArena image links typically point to full-size images
                if '.jpg' in href or '.png' in href or '.webp' in href:
                    # Make absolute URL
                    img_url = urljoin('https://www.gsmarena.com/', href)
                    
                    if img_url not in image_urls:
                        image_urls.append(img_url)
                        
                        if len(image_urls) >= max_images:
                            break
        
        # If no images found in pictures-list, try finding img tags
        if len(image_urls) <= 1:  # Only has main image or none
            print(f"      Few images found, trying additional img tags...")
            
            if pictures_list:
                img_tags = pictures_list.find_all('img')
            else:
                # Try the whole page
                img_tags = soup.find_all('img')
            
            for img in img_tags:
                src = img.get('src', '')
                
                # Skip very small images (icons, logos, etc.)
                if any(skip in src.lower() for skip in ['icon', 'logo', 'sprite', 'button', 'blank']):
                    continue
                
                # Look for actual phone images
                if src and ('.jpg' in src or '.png' in src or '.webp' in src):
                    # Make absolute URL
                    img_url = urljoin('https://www.gsmarena.com/', src)
                    
                    # Try to get larger version if it's a thumbnail
                    if '/vv/bigpic/' in img_url or '/vv/pics/' in img_url:
                        # Already a good quality image
                        pass
                    elif 'thumb' in img_url.lower():
                        # Try to convert thumbnail to full size
                        img_url = img_url.replace('thumb', 'pics')
                    
                    if img_url not in image_urls:
                        image_urls.append(img_url)
                        
                        if len(image_urls) >= max_images:
                            break
        
        return image_urls[:max_images]
        
    except Exception as e:
        print(f"      ✗ Error scraping images: {e}")
        return []

def download_phone_images(phone_name, spec_url, headers, images_dir='images', max_images=5):
    """
    Download up to max_images for a phone with clean naming
    Returns: list of local image paths and clean phone info
    """
    print(f"    Constructing pictures URL...")
    
    # Clean the phone name for better folder structure
    clean_info = clean_phone_name(phone_name)
    safe_name = clean_info['safe_name']
    display_name = clean_info['display_name']
    
    print(f"    Original name: {phone_name}")
    print(f"    Clean name: {display_name}")
    print(f"    Safe name: {safe_name}")
    
    # Construct pictures URL
    pictures_url = construct_pictures_url(spec_url)
    
    if not pictures_url:
        print(f"      ✗ Could not construct pictures URL")
        return [], clean_info
    
    print(f"    ✓ Pictures URL: {pictures_url}")
    
    # Scrape image URLs
    print(f"    Scraping images from #pictures-list and .specs-photo-main...")
    image_urls = scrape_images_from_pictures_page(pictures_url, headers, max_images)
    
    if not image_urls:
        print(f"      ✗ No images found")
        return [], clean_info
    
    print(f"    ✓ Found {len(image_urls)} image URLs")
    
    # Create phone-specific directory with clean name
    phone_dir = os.path.join(images_dir, safe_name)
    os.makedirs(phone_dir, exist_ok=True)
    
    # Download images with clean naming
    downloaded_paths = []
    print(f"    Downloading images with clean names...")
    
    for idx, img_url in enumerate(image_urls, 1):
        # Get file extension from URL
        parsed_url = urlparse(img_url)
        ext = os.path.splitext(parsed_url.path)[1]
        
        # If no extension or weird extension, default to .jpg
        if not ext or ext not in ['.jpg', '.jpeg', '.png', '.webp']:
            ext = '.jpg'
        
        # Create clean filename - use descriptive names
        if idx == 1:
            filename = f"main{ext}"  # Just "main.jpg" instead of long name
        else:
            filename = f"angle_{idx}{ext}"  # "angle_2.jpg", "angle_3.jpg", etc.
        
        save_path = os.path.join(phone_dir, filename)
        
        print(f"      [{idx}/{len(image_urls)}] {filename}...", end=' ')
        
        if download_image(img_url, save_path, headers):
            downloaded_paths.append(save_path)
            file_size = os.path.getsize(save_path) / 1024  # KB
            print(f"✓ ({file_size:.1f} KB)")
        else:
            print(f"✗")
        
        # Small delay between image downloads
        time.sleep(0.5)
    
    return downloaded_paths, clean_info

def process_phones_from_csv(csv_file, images_dir='images', max_phones=None, 
                            max_images_per_phone=5, delay=2, start_from=0):
    """
    Read phones from CSV and download images for each with clean naming
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Referer': 'https://www.gsmarena.com/',
        'Upgrade-Insecure-Requests': '1'
    }
    
    # Read CSV file
    print(f"Reading phones from {csv_file}...")
    phones = []
    
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Try to find spec_url in different possible column names
                spec_url = row.get('spec_url') or row.get('_metadata - spec_url') or row.get('review_url')
                
                if 'phone_name' in row and spec_url:
                    phones.append({
                        'phone_name': row['phone_name'],
                        'spec_url': spec_url
                    })
    except Exception as e:
        print(f"✗ Error reading CSV: {e}")
        return {}
    
    print(f"Found {len(phones)} phones in CSV")
    
    # Apply filters
    if start_from > 0:
        phones = phones[start_from:]
        print(f"Starting from phone #{start_from + 1}")
    
    if max_phones:
        phones = phones[:max_phones]
        print(f"Limiting to {max_phones} phones")
    
    print("=" * 80)
    
    # Create main images directory
    os.makedirs(images_dir, exist_ok=True)
    
    # Process each phone
    results = {}
    successful = 0
    failed = 0
    
    for idx, phone in enumerate(phones, 1):
        phone_name = phone['phone_name']
        spec_url = phone['spec_url']
        
        print(f"\n[{idx}/{len(phones)}] {phone_name}")
        
        if not spec_url:
            print(f"  ✗ No spec URL found, skipping...")
            failed += 1
            continue
        
        print(f"  Spec URL: {spec_url}")
        
        # Download images with clean naming
        image_paths, clean_info = download_phone_images(
            phone_name=phone_name,
            spec_url=spec_url,
            headers=headers,
            images_dir=images_dir,
            max_images=max_images_per_phone
        )
        
        if image_paths:
            results[phone_name] = {
                'spec_url': spec_url,
                'image_count': len(image_paths),
                'image_paths': image_paths,
                'clean_info': clean_info
            }
            print(f"  ✓ Successfully downloaded {len(image_paths)} images")
            print(f"  ✓ Clean name: {clean_info['display_name']}")
            successful += 1
        else:
            print(f"  ✗ Failed to download images")
            failed += 1
        
        # Delay before next phone
        if idx < len(phones):
            print(f"  Waiting {delay} seconds...")
            time.sleep(delay)
    
    # Summary
    print("\n" + "=" * 80)
    print(f"\n✓ Image download complete!")
    print(f"  Successful: {successful}/{len(phones)}")
    print(f"  Failed: {failed}/{len(phones)}")
    print(f"  Total images downloaded: {sum(r['image_count'] for r in results.values())}")
    print(f"  Images saved to: {os.path.abspath(images_dir)}")
    print("=" * 80)
    
    return results

def save_image_manifest(results, filename='image_manifest.json'):
    """
    Save a manifest of downloaded images with clean naming info
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Image manifest saved to {filename}")
        return True
    except Exception as e:
        print(f"\n✗ Error saving manifest: {e}")
        return False

if __name__ == "__main__":
    print("GSMArena Image Downloader - Clean Naming Edition")
    print("=" * 80)
    
    # Configuration
    INPUT_CSV = "gsmarena_specifications.csv"  # CSV with spec_url or review_url column
    IMAGES_DIR = "images"                      # Directory to save images
    MAX_PHONES = None                          # Set to None for all phones, or a number to limit
    MAX_IMAGES_PER_PHONE = 5                   # Maximum images per phone
    DELAY = 3                                  # Delay between phones (seconds)
    START_FROM = 0                             # Start from this index
    
    print(f"\nConfiguration:")
    print(f"  Input CSV: {INPUT_CSV}")
    print(f"  Images Directory: {IMAGES_DIR}")
    print(f"  Max Phones: {MAX_PHONES if MAX_PHONES else 'All'}")
    print(f"  Max Images per Phone: {MAX_IMAGES_PER_PHONE}")
    print(f"  Delay: {DELAY} seconds")
    print(f"  Start From: Phone #{START_FROM + 1}")
    print()
    
    # Process phones and download images
    results = process_phones_from_csv(
        csv_file=INPUT_CSV,
        images_dir=IMAGES_DIR,
        max_phones=5,  # Test with 5 phones first
        max_images_per_phone=MAX_IMAGES_PER_PHONE,
        delay=DELAY,
        start_from=START_FROM
    )
    
    # Save manifest
    if results:
        save_image_manifest(results)
        print(f"\n{'='*80}")
        print(f"✓ Successfully processed {len(results)} phones!")
        print(f"{'='*80}")
        
        # Print new directory structure
    #     print("\nNew directory structure (clean names):")
    #     print(f"  {IMAGES_DIR}/")
    #     for phone_name in list(results.keys())[:3]:  # Show first 3
    #         clean_info = results[phone_name]['clean_info']
    #         img_count = results[phone_name]['image_count']
    #         print(f"    ├── {clean_info['safe_name']}/")
    #         print(f"    │   ├── main.jpg")
    #         for i in range(2, img_count + 1):
    #             print(f"    │   {'├──' if i < img_count else '└──'} angle_{i}.jpg")
    #     if len(results) > 3:
    #         print(f"    └── ... ({len(results) - 3} more phones)")
    # else:
    #     print("\n✗ No images downloaded.")
    #     print("\nTroubleshooting:")
    #     print("  1. Check that the CSV file exists and has 'spec_url' column")
    #     print("  2. Verify spec URLs are in format: https://www.gsmarena.com/phone_name-12345.php")
    #     print("  3. Check your internet connection")
    #     print("  4. Try increasing DELAY if rate-limited")